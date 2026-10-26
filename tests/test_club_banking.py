from hashlib import sha256
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from time import time
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from cryptography.fernet import Fernet
from flask import Flask

from club_auth import bind_member, init_auth
from club_banking import db, init_banking, load_link, save_link, trusted_authorization_url


class ClubBankingTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / 'templates'))
        self.app.config.update(TESTING=True, SECRET_KEY='test-only', GOOGLE_CLIENT_ID='test',
            GOOGLE_CLIENT_SECRET='test', GOOGLE_REDIRECT_URI='http://127.0.0.1:5000/auth/google/callback',
            CLUB_MEMBERS='owner@example.com,member@example.com', CLUB_DATABASE=str(Path(self.temp.name) / 'club.sqlite3'),
            ENABLE_BANKING_APPLICATION_ID=str(uuid4()), ENABLE_BANKING_PRIVATE_KEY_PATH='test-only.pem',
            ENABLE_BANKING_ADMIN_EMAIL='owner@example.com', ENABLE_BANKING_ENVIRONMENT='SANDBOX',
            ENABLE_BANKING_ENCRYPTION_KEY=Fernet.generate_key().decode(),
            ENABLE_BANKING_REDIRECT_URI='http://127.0.0.1:5000/bank/callback')
        self.app.add_url_rule('/', 'home', lambda: 'Home')
        init_auth(self.app)
        init_banking(self.app)
        self.client = self.app.test_client()
        self.account_id, self.session_id = str(uuid4()), str(uuid4())

    def login(self, email='owner@example.com'):
        with self.app.app_context():
            bind_member(email, 'google-' + email)
        with self.client.session_transaction() as session:
            session['member'] = {'email': email, 'subject': 'google-' + email, 'provider': 'google', 'name': 'Test'}
            session['csrf_token'] = 'test-csrf'

    def link(self, selected=True):
        return {'session_id': self.session_id,
                'accounts': [{'id': self.account_id, 'label': 'Klubbkonto'}],
                'selected': self.account_id if selected else None,
                'application_id': self.app.config['ENABLE_BANKING_APPLICATION_ID'],
                'environment': 'SANDBOX', 'admin_email': 'owner@example.com'}

    def test_guests_cannot_fetch_balance_or_start_bank_connection(self):
        with patch('club_banking.api') as api:
            self.assertEqual(self.client.get('/klubben/bank/saldo').status_code, 302)
            self.assertEqual(self.client.post('/klubben/bank/anslut').status_code, 302)
            api.assert_not_called()

    def test_members_can_see_selected_balance_but_not_manage_the_bank_connection(self):
        self.login('member@example.com')
        with self.app.app_context():
            save_link(self.link())
        with patch('club_banking.api') as api:
            self.assertEqual(self.client.post('/klubben/bank/anslut', data={'csrf_token':'test-csrf'}).status_code, 403)
            api.assert_not_called()
            api.side_effect = [{'status':'AUTHORIZED','accounts':[self.account_id]},
                               {'balances':[{'balance_amount':{'amount':'100','currency':'SEK'},'balance_type':'ITAV'}]}]
            response=self.client.get('/klubben/bank/saldo')
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.get_json()['balances'][0]['amount'],'100')
            self.assertFalse(response.get_json()['admin'])
            self.assertNotIn(self.session_id,response.get_data(as_text=True))
        html=self.client.get('/klubben').get_data(as_text=True)
        self.assertIn('id="klubbkassan"',html)
        self.assertNotIn('action="/klubben/bank/anslut"',html)

    def test_owner_sees_bank_section_and_script(self):
        self.login()
        response=self.client.get('/klubben')
        self.assertEqual(response.status_code,200)
        self.assertIn('Sandbox',response.get_data(as_text=True))
        self.assertIn('id="klubbkassan"',response.get_data(as_text=True))

    def test_bank_connection_requires_csrf_and_registered_callback(self):
        self.login()
        with patch('club_banking.api') as api:
            self.assertEqual(self.client.post('/klubben/bank/anslut').status_code, 400)
            api.assert_not_called()
            api.return_value = {'active': True, 'environment':'SANDBOX', 'redirect_urls':[]}
            response=self.client.post('/klubben/bank/anslut',data={'csrf_token':'test-csrf'})
            self.assertEqual(response.status_code,302)
            self.assertEqual(api.call_count,1)

    def test_invalid_state_does_not_exchange_bank_code(self):
        self.login()
        with patch('club_banking.api') as api:
            response = self.client.get('/bank/callback?state=wrong&code=fake')
            self.assertEqual(response.status_code,400)
            api.assert_not_called()

    def test_production_callback_alias_uses_the_same_state_protection(self):
        self.login()
        with patch('club_banking.api') as api:
            self.assertEqual(self.client.get('/callback?state=wrong&code=fake').status_code,400)
            api.assert_not_called()

    def test_callback_consumes_state_once_and_encrypts_session(self):
        self.login()
        state='test-state'
        hashed=sha256(state.encode()).hexdigest()
        with self.client.session_transaction() as session:
            session['bank_state']=hashed
        with self.app.app_context():
            database=db()
            database.execute('INSERT INTO bank_pending VALUES(?,?,?)',(hashed,'google-owner@example.com',int(time())+600))
            database.commit()
        response={'session_id':self.session_id,'accounts':[{'uid':self.account_id,'name':'Klubbkonto'}]}
        with patch('club_banking.api',return_value=response) as api:
            self.assertEqual(self.client.get('/bank/callback?state=test-state&code=test-code').status_code,302)
            self.assertEqual(self.client.get('/bank/callback?state=test-state&code=test-code').status_code,400)
            self.assertEqual(api.call_count,1)
        with self.app.app_context():
            encrypted=db().execute('SELECT encrypted FROM bank_connection').fetchone()[0]
            self.assertNotIn(self.session_id,encrypted)
            self.assertNotIn(self.account_id,encrypted)
            self.assertEqual(load_link()['selected'], self.account_id)
        with self.client.session_transaction() as session:
            self.assertNotIn('bank_state',session)
            self.assertNotIn('session_id',session)

    def test_balance_is_decimal_string_and_never_exposes_bank_session(self):
        self.login()
        with self.app.app_context():
            save_link(self.link())
        data=[{'status':'AUTHORIZED','accounts':[self.account_id]},
              {'balances':[{'balance_amount':{'amount':'1234.56','currency':'SEK'},'balance_type':'ITAV','name':'Available'}]}]
        with patch('club_banking.api',side_effect=data):
            response=self.client.get('/klubben/bank/saldo')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.get_json()['balances'][0]['amount'],'1234.56')
        self.assertNotIn(self.session_id,response.get_data(as_text=True))
        self.assertIn('no-store',response.headers['Cache-Control'])

    def test_revoked_bank_session_never_fetches_balances(self):
        self.login()
        with self.app.app_context():
            save_link(self.link())
        with patch('club_banking.api',return_value={'status':'REVOKED','accounts':[]}) as api:
            self.assertEqual(self.client.get('/klubben/bank/saldo').status_code,502)
            self.assertEqual(api.call_count,1)

    def test_cannot_select_an_account_outside_the_authorized_session(self):
        self.login()
        with self.app.app_context():
            save_link(self.link(selected=False))
        self.assertEqual(self.client.post('/klubben/bank/valj-konto',data={
            'csrf_token':'test-csrf','share_confirm':'yes','account_id':str(uuid4())}).status_code,400)

    def test_accounts_not_selected_by_owner_are_not_exposed_to_members(self):
        self.login('member@example.com')
        with self.app.app_context():
            save_link(self.link(selected=False))
        response=self.client.get('/klubben/bank/saldo')
        self.assertEqual(response.get_json()['accounts'],[])
        self.assertNotIn(self.account_id,response.get_data(as_text=True))

    def test_selection_requires_explicit_sharing_confirmation(self):
        self.login()
        with self.app.app_context():
            save_link(self.link(selected=False))
        self.assertEqual(self.client.post('/klubben/bank/valj-konto',data={
            'csrf_token':'test-csrf','account_id':self.account_id}).status_code,400)
        response=self.client.post('/klubben/bank/valj-konto',data={
            'csrf_token':'test-csrf','share_confirm':'yes','account_id':self.account_id})
        self.assertEqual(response.status_code,302)

    def test_authorization_url_accepts_current_and_legacy_provider_hosts_only(self):
        for url in ('https://auth.enablebanking.com/ais/start?sessionid=test',
                    'https://tilisy.enablebanking.com/ais/start?sessionid=test'):
            self.assertTrue(trusted_authorization_url(url))
        for url in ('http://tilisy.enablebanking.com/start', 'https://evil.example/start',
                    'https://auth.enablebanking.com.evil.example/start',
                    'https://auth.enablebanking.com@evil.example/start',
                    'https://user@auth.enablebanking.com/start',
                    'https://auth.enablebanking.com:444/start',
                    'https://auth.enablebanking.com/\nstart', None):
            self.assertFalse(trusted_authorization_url(url))

    def test_connect_accepts_legacy_host_and_preserves_oauth_state(self):
        self.login()
        metadata={'active':True,'environment':'SANDBOX','redirect_urls':[self.app.config['ENABLE_BANKING_REDIRECT_URI']]}
        destination='https://tilisy.enablebanking.com/ais/start?sessionid=test'
        directory={'aspsps':[{'name':'Nordea','country':'SE','maximum_consent_validity':15552000}]}
        with patch('club_banking.api',side_effect=[metadata,directory,{'url':destination}]) as api:
            response=self.client.post('/klubben/bank/anslut',data={'csrf_token':'test-csrf'})
            self.assertEqual(response.location,destination)
            state=api.call_args.args[2]['state']
        with self.client.session_transaction() as session:
            self.assertEqual(session['bank_state'],sha256(state.encode()).hexdigest())

    def test_multiple_accounts_still_require_explicit_selection(self):
        self.login()
        state='multiple-accounts-state'
        hashed=sha256(state.encode()).hexdigest()
        with self.client.session_transaction() as session:
            session['bank_state']=hashed
        with self.app.app_context():
            database=db()
            database.execute('INSERT INTO bank_pending VALUES(?,?,?)',(hashed,'google-owner@example.com',int(time())+600))
            database.commit()
        response={'session_id':self.session_id,'accounts':[{'uid':self.account_id,'name':'First'},
                                                            {'uid':str(uuid4()),'name':'Second'}]}
        with patch('club_banking.api',return_value=response):
            self.assertEqual(self.client.get('/callback?state='+state+'&code=test-code').status_code,302)
        with self.app.app_context():
            self.assertIsNone(load_link()['selected'])

    def test_healthy_saved_connection_is_reused_without_new_bank_authorization(self):
        self.login()
        with self.app.app_context():
            save_link(self.link())
        with patch('club_banking.api',return_value={'status':'AUTHORIZED','accounts':[self.account_id]}) as api:
            response=self.client.post('/klubben/bank/anslut',data={'csrf_token':'test-csrf'})
            self.assertEqual(response.status_code,302)
            api.assert_called_once_with('GET','/sessions/'+self.session_id)

    def test_request_uses_bank_maximum_instead_of_one_day(self):
        self.login()
        metadata={'active':True,'environment':'SANDBOX','redirect_urls':[self.app.config['ENABLE_BANKING_REDIRECT_URI']]}
        directory={'aspsps':[{'name':'Nordea','country':'SE','maximum_consent_validity':15552000}]}
        before=datetime.now(timezone.utc)
        with patch('club_banking.api',side_effect=[metadata,directory,{'url':'https://auth.enablebanking.com/start'}]) as api:
            self.client.post('/klubben/bank/anslut',data={'csrf_token':'test-csrf'})
            access=api.call_args.args[2]['access']
        duration=(datetime.fromisoformat(access['valid_until'])-before).total_seconds()
        self.assertGreaterEqual(duration,15552000)
        self.assertLess(duration,15552005)
        self.assertIs(access['transactions'],False)
        self.assertIs(access['balances'],True)

    def test_balance_cache_is_shared_without_sharing_owner_permissions(self):
        self.login()
        with self.app.app_context():
            save_link(self.link())
        payload=[{'status':'AUTHORIZED','accounts':[self.account_id]},
                 {'balances':[{'balance_amount':{'amount':'2500.50','currency':'SEK'},'balance_type':'ITAV'}]}]
        with patch('club_banking.api',side_effect=payload) as api:
            first=self.client.get('/klubben/bank/saldo').get_json()
            self.assertTrue(first['admin'])
            self.login('member@example.com')
            second=self.client.get('/klubben/bank/saldo').get_json()
            self.assertFalse(second['admin'])
            self.assertEqual(second['balances'],first['balances'])
            self.assertEqual(api.call_count,2)

    def test_ordinary_network_failure_does_not_request_new_bank_login(self):
        self.login()
        with self.app.app_context():
            save_link(self.link())
        from club_banking import BankError
        with patch('club_banking.api',side_effect=BankError('Temporary error')):
            response=self.client.get('/klubben/bank/saldo')
        self.assertFalse(response.get_json()['needs_reconnect'])

    def test_revocation_returns_reconnect_flag(self):
        self.login()
        with self.app.app_context():
            save_link(self.link())
        with patch('club_banking.api',return_value={'status':'EXPIRED','accounts':[]}):
            response=self.client.get('/klubben/bank/saldo')
        self.assertTrue(response.get_json()['needs_reconnect'])
