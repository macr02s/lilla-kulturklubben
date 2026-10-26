from unittest import TestCase

from app_config import auth_settings


class AppConfigTests(TestCase):
    def test_local_default(self):
        settings = auth_settings({})
        self.assertEqual(settings["GOOGLE_REDIRECT_URI"], "http://127.0.0.1:5000/auth/google/callback")
        self.assertFalse(settings["SESSION_COOKIE_SECURE"])

    def test_render_default_uses_render_address(self):
        settings = auth_settings({"RENDER_EXTERNAL_URL": "https://lilla-kulturklubben.onrender.com/"})
        self.assertEqual(settings["GOOGLE_REDIRECT_URI"], "https://lilla-kulturklubben.onrender.com/auth/google/callback")
        self.assertTrue(settings["SESSION_COOKIE_SECURE"])

    def test_localhost_cookie_default_and_explicit_override(self):
        settings = auth_settings({"PUBLIC_BASE_URL": "http://localhost:5000"})
        self.assertFalse(settings["SESSION_COOKIE_SECURE"])
        settings = auth_settings({"PUBLIC_BASE_URL": "http://localhost:5000", "SESSION_COOKIE_SECURE": "true"})
        self.assertTrue(settings["SESSION_COOKIE_SECURE"])

    def test_explicit_remote_callback_uses_secure_cookie_despite_local_base(self):
        settings = auth_settings({"PUBLIC_BASE_URL": "http://localhost:5000",
                                  "GOOGLE_REDIRECT_URI": "https://club.example/auth/google/callback"})
        self.assertTrue(settings["SESSION_COOKIE_SECURE"])

    def test_custom_domain_overrides_render_without_code_change(self):
        settings = auth_settings({"PUBLIC_BASE_URL": "https://klubben.example/",
                                  "RENDER_EXTERNAL_URL": "https://lilla-kulturklubben.onrender.com"})
        self.assertEqual(settings["GOOGLE_REDIRECT_URI"], "https://klubben.example/auth/google/callback")

    def test_explicit_callback_has_precedence(self):
        settings = auth_settings({"PUBLIC_BASE_URL": "https://klubben.example",
                                  "GOOGLE_REDIRECT_URI": "https://override.example/auth/google/callback"})
        self.assertEqual(settings["GOOGLE_REDIRECT_URI"], "https://override.example/auth/google/callback")

    def test_blank_override_uses_public_domain(self):
        settings = auth_settings({"PUBLIC_BASE_URL": "https://klubben.example", "GOOGLE_REDIRECT_URI": " "})
        self.assertEqual(settings["GOOGLE_REDIRECT_URI"], "https://klubben.example/auth/google/callback")

    def test_persistent_database_path_is_configurable(self):
        self.assertEqual(auth_settings({"CLUB_DATABASE": "/var/data/club.sqlite3"})["CLUB_DATABASE"], "/var/data/club.sqlite3")

    def test_invalid_public_addresses_fail_closed(self):
        for base in ("http://club.example", "https://club.example/path", "https://user@club.example",
                     "https://club.example?next=evil", "//club.example", "https://club.example#hash"):
            with self.subTest(base=base), self.assertRaises(ValueError):
                auth_settings({"PUBLIC_BASE_URL": base})
