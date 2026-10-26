from unittest import TestCase
from unittest.mock import patch

import billetto_events as billetto
import club_events as combined
from app import app
import test_club_auth as auth_fixture


def raw(source='Ticketmaster', title='Kent', venue='3Arena', day='2027-03-15', time='19:00'):
    url={'Ticketmaster':'https://www.ticketmaster.se/event/123', 'Visit Stockholm':'https://www.visitstockholm.se/event/kent/', 'Billetto':'https://billetto.se/e/kent-biljetter-123?utm_source=publisher&utm_campaign=events'}[source]
    return {'title':title,'venue':venue,'start':day,'end':day,'time':time,'city':'Stockholm','url':url,'category':'Music'}


def normalized(source='Ticketmaster', **kw):
    return combined.normalize(raw(source,**kw),source)


class CombinedEventsTests(TestCase):
    def setUp(self):
        combined._cache.clear()

    @patch.object(combined,'_billetto_catalog')
    @patch.object(combined,'_ticketmaster_catalog')
    @patch.object(combined,'_visit_catalog')
    def test_home_and_member_search_use_identical_merged_results(self, visit, tm, billetto):
        visit.return_value={'events':[raw('Visit Stockholm',time='')]}
        tm.return_value={'events':[raw('Ticketmaster')]}
        billetto.return_value={'events':[raw('Billetto')]}
        config={'TICKETMASTER_API_KEY':'test-ticketmaster','BILLETTO_API_KEYPAIR':'test-key:test-secret'}
        query='?from_month=2027-01&to_month=2027-03'
        with patch.dict(app.config,config):
            client=app.test_client()
            page=client.get('/').get_data(as_text=True)
            self.assertEqual(page.count('data-events-widget'),1)
            self.assertEqual(page.count('data-role="date-filter"'),1)
            self.assertIn('data-endpoint="/api/combined-events"',page)
            public=client.get('/api/combined-events'+query)
            self.assertEqual(public.status_code,200)
            data=public.get_json()
            self.assertEqual(data['count'],1)
            self.assertTrue(data['combined'])
            self.assertEqual(data['events'][0]['link_source'],'Ticketmaster')
            self.assertEqual(set(data['events'][0]['sources']),{'Visit Stockholm','Ticketmaster','Billetto'})
            helper=auth_fixture.ClubAuthTests();helper.setUp()
            try:
                helper.app.config.update(config)
                helper.sign_in()
                member=helper.client.get('/klubben/evenemang'+query)
                self.assertEqual(member.get_json(),data)
                self.assertEqual(helper.client.get('/klubben').get_data(as_text=True).count('data-events-widget'),1)
            finally:
                helper.doCleanups();helper.temp.cleanup()

    @patch.object(combined,'get_events')
    def test_invalid_public_range_does_not_fetch_any_sources(self, fetch):
        response=app.test_client().get('/api/combined-events?from_month=2027-09&to_month=2027-01')
        self.assertEqual(response.status_code,400)
        fetch.assert_not_called()

    def test_three_sources_merge_and_prefer_ticket_link(self):
        events=[normalized('Visit Stockholm',time=''),normalized('Ticketmaster'),normalized('Billetto')]
        result=combined.deduplicate(events)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['link_source'],'Ticketmaster')
        self.assertEqual(result[0]['sources'],['Billetto','Ticketmaster','Visit Stockholm'])
        self.assertEqual(result[0]['time'],'19:00')
        self.assertEqual(events[0]['sources'],['Visit Stockholm'])

    def test_titles_ignore_case_accents_punctuation_and_whitespace(self):
        events=[normalized(title='KENT!'),normalized('Visit Stockholm',title=' Kent  ',time='')]
        self.assertEqual(len(combined.deduplicate(events)),1)

    def test_different_dates_venues_and_performances_are_not_merged(self):
        events=[normalized(time='14:00'),normalized(time='19:00'),normalized('Visit Stockholm',time=''),
                normalized(day='2027-03-16'),normalized(venue='Other venue')]
        self.assertEqual(len(combined.deduplicate(events)),5)

    def test_missing_venue_does_not_match_unrelated_source(self):
        events=[normalized(venue=''),normalized('Visit Stockholm',venue='',time='')]
        self.assertEqual(len(combined.deduplicate(events)),2)

    def test_strict_stockholm_filter_and_undated_events(self):
        for city in ('Solna','Johanneshov',None,''):
            event=raw();event['city']=city
            self.assertIsNone(combined.normalize(event,'Ticketmaster'))
        event=raw();event['start']=None
        self.assertIsNone(combined.normalize(event,'Ticketmaster'))
        event=raw();event['url']='https://evil.example/event'
        self.assertIsNone(combined.normalize(event,'Ticketmaster'))

    def test_billetto_tracking_parameters_survive_normalization_and_merging(self):
        event=normalized('Billetto')
        result=combined.deduplicate([event,normalized('Visit Stockholm',time='')])[0]
        self.assertEqual(result['url'],event['url'])
        self.assertIn('utm_source=publisher',result['url'])

    @patch.object(combined,'_ticketmaster_catalog')
    @patch.object(combined,'_visit_catalog')
    def test_deduplication_happens_before_counts_filters_and_pagination(self, visit, tm):
        tm.return_value={'events':[raw(title='Event '+str(i)) for i in range(12)]}
        visit.return_value={'events':[raw('Visit Stockholm',title='Event '+str(i),time='') for i in range(12)]}
        settings={'TICKETMASTER_API_KEY':'test-key'}
        first=combined.get_events(settings,start_date='2027-01-01',end_date='2027-03-31')
        second=combined.get_events(settings,'music',page=2,start_date='2027-01-01',end_date='2027-03-31')
        self.assertEqual(first['count'],12)
        self.assertEqual(len(first['events']),9)
        self.assertEqual(len(second['events']),3)
        self.assertIsNone(second['next'])
        self.assertEqual(visit.call_count,1);self.assertEqual(tm.call_count,1)
        combined.get_events(settings,start_date='2027-07-01',end_date='2027-09-30')
        self.assertEqual(visit.call_count,2)

    @patch.object(combined,'_ticketmaster_catalog')
    @patch.object(combined,'_visit_catalog',side_effect=combined.visit.SourceUnavailable())
    def test_single_source_failure_does_not_hide_other_events(self, visit, tm):
        tm.return_value={'events':[raw()]}
        result=combined.get_events({'TICKETMASTER_API_KEY':'test-key'})
        self.assertEqual(result['count'],1)
        self.assertEqual(result['unavailable_sources'],['Visit Stockholm'])

    def test_combined_route_requires_membership_and_valid_months(self):
        helper=auth_fixture.ClubAuthTests();helper.setUp()
        try:
            self.assertEqual(helper.client.get('/klubben/evenemang').status_code,302)
            self.assertNotIn('id="club-events"',helper.client.get('/klubben').get_data(as_text=True))
            helper.sign_in()
            self.assertIn('id="club-events"',helper.client.get('/klubben').get_data(as_text=True))
            with patch.object(combined,'get_events',return_value={'events':[],'count':0}) as get:
                response=helper.client.get('/klubben/evenemang?from_month=2027-01&to_month=2027-03')
                self.assertEqual(response.status_code,200)
                self.assertIn('no-store',response.headers['Cache-Control'])
                self.assertEqual(get.call_args.args[-2:],('2027-01-01','2027-03-31'))
                self.assertEqual(helper.client.get('/klubben/evenemang?from_month=2027-09&to_month=2027-01').status_code,400)
                self.assertEqual(get.call_count,1)
        finally:
            helper.doCleanups();helper.temp.cleanup()


def billetto_raw():
    return {'id':'123','title':'Concert','state':'published','url':'https://billetto.se/e/concert-biljetter-123?utm_source=club&utm_campaign=events',
            'startdate':'2027-03-31T22:30:00Z','enddate':'2027-04-01T00:00:00Z',
            'location':{'name':'Venue','city':'Stockholm','country_code':'SE'},'image_link':'https://example.com/banner.jpg'}


class BillettoEventsTests(TestCase):
    def test_live_payload_field_names_and_categories(self):
        data=billetto_raw()
        data['location']['location_name']='Actual venue'
        data['location'].pop('name')
        data['categorization']={'category':'performing_arts','category_localized':'Scen- & Bildkonst',
                                'subcategory':'literary_arts','subcategory_localized':'Literature'}
        event=billetto.normalize(data)
        self.assertEqual(event['venue'],'Actual venue')
        self.assertEqual(event['genre'],'Literature')
        self.assertEqual(combined.normalize(event,'Billetto')['category_id'],'stage')

    @patch.object(billetto.requests,'get')
    def test_live_list_pagination_uses_after_id_cursor(self, get):
        get.return_value.status_code=200;get.return_value.content=b'{}'
        second=billetto_raw();second['id']='456'
        get.return_value.json.side_effect=[{'data':[billetto_raw()],'has_more':True,'total':2},
                                          {'data':[second],'has_more':False,'total':2}]
        data=billetto.get_catalog('test-key:test-secret')
        self.assertEqual(len(data['events']),2)
        self.assertEqual(get.call_args.kwargs['params'],{'limit':100,'region':'Stockholm','after':'123'})
        self.assertEqual(get.call_args.args[0],billetto.API)

    def test_timezone_preserved_tracking_and_no_hotlinking_banner(self):
        result=billetto.normalize(billetto_raw())
        self.assertEqual(result['start'],'2027-04-01')
        self.assertEqual(result['time'],'00:30')
        self.assertIn('utm_campaign=events',result['url'])
        self.assertEqual(result['image'],'')
        for city in ('Solna',None):
            data=billetto_raw();data['location']['city']=city
            self.assertIsNone(billetto.normalize(data))
        data=billetto_raw();data['state']='draft'
        self.assertIsNone(billetto.normalize(data))

    @patch.object(billetto.requests,'get')
    def test_header_auth_and_pagination(self, get):
        first=get.return_value
        first.status_code=200;first.content=b'{}'
        first.json.side_effect=[{'data':[billetto_raw()],'pagination':{'has_more':True,'next_url':'/api/v3/public/events?next=100'}},
                                {'data':[],'pagination':{'has_more':False}}]
        result=billetto.get_catalog('test-key:test-secret','2027-04-01','2027-04-30')
        self.assertEqual(len(result['events']),1)
        self.assertEqual(get.call_count,2)
        self.assertEqual(get.call_args.kwargs['headers'],{'Api-Keypair':'test-key:test-secret'})
        self.assertFalse(get.call_args.kwargs['allow_redirects'])
        self.assertNotIn('test-secret',str(result))

    @patch.object(billetto.requests,'get')
    def test_untrusted_next_page_never_receives_keypair(self, get):
        get.return_value.status_code=200;get.return_value.content=b'{}'
        get.return_value.json.return_value={'data':[],'has_more':True,'next_url':'https://evil.example/api/v3/public/events'}
        with self.assertRaises(billetto.SourceUnavailable):billetto.get_catalog('test-key:test-secret')
        self.assertEqual(get.call_count,1)

    @patch.object(billetto.requests,'get')
    def test_unconfigured_credentials_make_no_requests(self, get):
        for value in ('','key-only',':secret','key:'):
            with self.assertRaises(billetto.SourceUnavailable):billetto.get_catalog(value)
        get.assert_not_called()
