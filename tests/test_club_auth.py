from pathlib import Path
from tempfile import TemporaryDirectory
from time import time
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from flask import Flask
from requests.exceptions import ConnectionError
from joserfc import jwt
from joserfc.jwk import RSAKey

from club_auth import init_auth, member_required
from club_banking import init_banking


class ClubAuthTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / "templates"))
        self.app.config.update(
            TESTING=True, SECRET_KEY="test-only-key", GOOGLE_CLIENT_ID="test-client",
            GOOGLE_CLIENT_SECRET="test-client-secret",
            GOOGLE_REDIRECT_URI="http://127.0.0.1:5000/auth/google/callback",
            CLUB_MEMBERS="anna@example.com, BO@example.com",
            CLUB_DATABASE=str(Path(self.temp.name) / "club.sqlite3"),
            SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
        )
        self.app.add_url_rule("/", "home", lambda: "Home")
        init_auth(self.app)
        init_banking(self.app)

        @self.app.get("/private-test")
        @member_required
        def private_test():
            return "private content"

        self.client = self.app.test_client()
        self.google = self.app.extensions["club_oauth"].google

    def token(self, email="anna@example.com", subject="google-123", **claims):
        return {"id_token": "validated-by-authlib-in-production",
                "userinfo": {"sub": subject, "email": email, "email_verified": True,
                             "given_name": "Anna", **claims}}

    def sign_in(self, **kwargs):
        with patch.object(self.google, "authorize_access_token", return_value=self.token(**kwargs)):
            return self.client.get("/auth/google/callback")

    def test_guest_only_sees_login_and_private_route_redirects(self):
        response = self.client.get("/klubben")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Logga in med Google", response.get_data(as_text=True))
        self.assertNotIn("anna@example.com", response.get_data(as_text=True))
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(self.client.get("/private-test").status_code, 302)

    def test_calendar_is_visible_only_to_current_members(self):
        self.app.config["CLUB_CALENDAR_ID"] = "club-calendar@group.calendar.google.com"
        guest = self.client.get("/klubben").get_data(as_text=True)
        self.assertNotIn("<iframe", guest)
        self.assertNotIn("club-calendar", guest)
        self.sign_in()
        html = self.client.get("/klubben").get_data(as_text=True)
        self.assertIn("<iframe", html)
        self.assertIn("src=club-calendar%40group.calendar.google.com", html)
        self.assertIn("ctz=Europe%2FStockholm", html)
        self.assertIn("mode=MONTH", html)
        self.assertIn("cid=club-calendar%40group.calendar.google.com", html)
        self.app.config["CLUB_MEMBERS"] = ""
        self.assertNotIn("<iframe", self.client.get("/klubben").get_data(as_text=True))

    def test_missing_calendar_does_not_break_member_page(self):
        self.sign_in()
        response = self.client.get("/klubben")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("<iframe", response.get_data(as_text=True))

    def test_calendar_id_is_encoded_as_data_not_html_or_an_external_url(self):
        self.app.config["CLUB_CALENDAR_ID"] = 'x&src=evil"><script>alert(1)</script>'
        self.sign_in()
        html = self.client.get("/klubben").get_data(as_text=True)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("x%26src%3Devil", html)

    def test_missing_configuration_fails_closed(self):
        for key in ("SECRET_KEY", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "CLUB_MEMBERS"):
            original = self.app.config[key]
            self.app.config[key] = ""
            self.assertEqual(self.client.get("/auth/google").status_code, 503)
            self.assertEqual(self.client.get("/auth/google/callback").status_code, 503)
            self.assertNotIn("Logga in med Google", self.client.get("/klubben").get_data(as_text=True))
            self.app.config[key] = original

    def test_authorization_redirect_uses_state_nonce_pkce_and_fixed_callback(self):
        metadata = {"authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
                    "token_endpoint": "https://oauth2.googleapis.com/token",
                    "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
                    "issuer": "https://accounts.google.com"}
        with patch.object(self.google, "load_server_metadata", return_value=metadata):
            response = self.client.get("/auth/google?next=https://evil.example")
        self.assertEqual(response.status_code, 302)
        params = parse_qs(urlsplit(response.location).query)
        self.assertEqual(params["redirect_uri"], [self.app.config["GOOGLE_REDIRECT_URI"]])
        for parameter in ("state", "nonce", "code_challenge"):
            self.assertTrue(params[parameter][0])
        self.assertEqual(params["code_challenge_method"], ["S256"])
        self.assertEqual(set(params["scope"][0].split()), {"openid", "email", "profile"})

    def test_missing_oauth_state_is_rejected_before_token_request(self):
        with patch.object(self.google, "fetch_access_token") as fetch:
            self.assertEqual(self.client.get("/auth/google/callback?code=fake&state=fake").status_code, 400)
        fetch.assert_not_called()

    def test_allowed_verified_member_can_access_member_content(self):
        self.assertEqual(self.sign_in().status_code, 302)
        response = self.client.get("/klubben")
        html = response.get_data(as_text=True)
        self.assertIn("anna@example.com", html)
        self.assertNotIn("Logga in med Google", html)
        self.assertEqual(self.client.get("/private-test").status_code, 200)
        with self.client.session_transaction() as session:
            self.assertEqual(session["member"]["subject"], "google-123")
            self.assertNotIn("id_token", session)
            self.assertNotIn("access_token", session)

    def test_uninvited_and_unverified_accounts_are_denied(self):
        for kwargs in ({"email": "outsider@example.com"}, {"email_verified": False},
                       {"email_verified": "true"}, {"subject": ""}):
            self.assertEqual(self.sign_in(**kwargs).status_code, 403)
            self.assertEqual(self.client.get("/private-test").status_code, 302)

    def test_membership_is_case_insensitive_and_google_subject_is_bound(self):
        self.assertEqual(self.sign_in(email="ANNA@EXAMPLE.COM").status_code, 302)
        self.assertEqual(self.sign_in(subject="another-google-account").status_code, 403)

    def test_removing_member_revokes_existing_session(self):
        self.sign_in()
        self.app.config["CLUB_MEMBERS"] = "bo@example.com"
        self.assertEqual(self.client.get("/private-test").status_code, 302)
        self.assertNotIn("anna@example.com", self.client.get("/klubben").get_data(as_text=True))

    def test_logout_requires_post_and_csrf_and_clears_session(self):
        self.sign_in()
        self.client.get("/klubben")
        self.assertEqual(self.client.get("/auth/logout").status_code, 405)
        self.assertEqual(self.client.post("/auth/logout").status_code, 400)
        with self.client.session_transaction() as session:
            csrf = session["csrf_token"]
        self.assertEqual(self.client.post("/auth/logout", data={"csrf_token": csrf}).status_code, 302)
        self.assertEqual(self.client.get("/private-test").status_code, 302)

    def test_provider_failure_is_friendly(self):
        with patch.object(self.google, "authorize_access_token", side_effect=ConnectionError("private diagnostics")):
            response = self.client.get("/auth/google/callback")
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("private diagnostics", response.get_data(as_text=True))

    def test_https_configuration_requires_secure_cookies(self):
        self.app.config["GOOGLE_REDIRECT_URI"] = "https://club.example/auth/google/callback"
        self.assertEqual(self.client.get("/auth/google").status_code, 503)

    def test_google_access_token_without_id_token_is_denied(self):
        token = self.token()
        del token["id_token"]
        with patch.object(self.google, "authorize_access_token", return_value=token):
            self.assertEqual(self.client.get("/auth/google/callback").status_code, 400)

    def test_real_oidc_validation_accepts_signed_token_and_rejects_invalid_claims(self):
        key = RSAKey.generate_key(2048, parameters={"kid": "test-key"})
        other_key = RSAKey.generate_key(2048, parameters={"kid": "test-key"})
        metadata = {"authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
                    "token_endpoint": "https://oauth2.googleapis.com/token",
                    "issuer": "https://accounts.google.com",
                    "id_token_signing_alg_values_supported": ["RS256"]}
        public_keys = {"keys": [key.as_dict(private=False)]}
        cases = [(None, {}, 302), (None, {"nonce": "wrong"}, 400),
                 (None, {"iss": "https://evil.example"}, 400),
                 (None, {"aud": "wrong-client"}, 400),
                 (None, {"exp": int(time()) - 3600}, 400),
                 (other_key, {}, 400)]
        for signing_key, overrides, expected in cases:
            with self.subTest(overrides=overrides, wrong_key=bool(signing_key)):
                with patch.object(self.google, "load_server_metadata", return_value=metadata):
                    redirect = self.client.get("/auth/google")
                    params = parse_qs(urlsplit(redirect.location).query)
                    claims = {"iss": metadata["issuer"], "sub": "google-123",
                              "aud": "test-client", "exp": int(time()) + 600,
                              "iat": int(time()), "nonce": params["nonce"][0],
                              "email": "anna@example.com", "email_verified": True, **overrides}
                    encoded = jwt.encode({"alg": "RS256", "kid": "test-key"}, claims, signing_key or key)
                    with patch.object(self.google, "fetch_access_token", return_value={"id_token": encoded, "access_token": "test-access-token"}), \
                            patch.object(self.google, "fetch_jwk_set", return_value=public_keys):
                        response = self.client.get("/auth/google/callback", query_string={"code": "test-code", "state": params["state"][0]})
                self.assertEqual(response.status_code, expected)
