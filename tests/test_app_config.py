from unittest import TestCase
from pathlib import Path
from tempfile import TemporaryDirectory

from app_config import auth_settings, runtime_environment


class AppConfigTests(TestCase):
    def test_local_default(self):
        settings = auth_settings({})
        self.assertEqual(settings["GOOGLE_REDIRECT_URI"], "http://127.0.0.1:5000/auth/google/callback")
        self.assertFalse(settings["SESSION_COOKIE_SECURE"])

    def test_render_default_uses_render_address(self):
        settings = auth_settings({"RENDER_EXTERNAL_URL": "https://lilla-kulturklubben.onrender.com/"})
        self.assertEqual(settings["GOOGLE_REDIRECT_URI"], "https://lilla-kulturklubben.onrender.com/auth/google/callback")
        self.assertTrue(settings["SESSION_COOKIE_SECURE"])

    def test_same_shared_values_work_locally_and_on_render(self):
        shared = {"SECRET_KEY": "test-only-secret", "GOOGLE_CLIENT_ID": "test-client",
                  "GOOGLE_CLIENT_SECRET": "test-secret", "CLUB_MEMBERS": "member@example.com",
                  "PUBLIC_BASE_URL": "", "GOOGLE_REDIRECT_URI": "", "SESSION_COOKIE_SECURE": ""}
        local = auth_settings(shared)
        hosted = auth_settings({**shared, "RENDER": "true", "RENDER_EXTERNAL_URL": "https://club.onrender.com"})
        self.assertEqual(local["GOOGLE_REDIRECT_URI"], "http://127.0.0.1:5000/auth/google/callback")
        self.assertFalse(local["SESSION_COOKIE_SECURE"])
        self.assertEqual(hosted["GOOGLE_REDIRECT_URI"], "https://club.onrender.com/auth/google/callback")
        self.assertTrue(hosted["SESSION_COOKIE_SECURE"])
        for key in ("SECRET_KEY", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "CLUB_MEMBERS"):
            self.assertEqual(local[key], hosted[key])

    def test_imported_legacy_local_settings_do_not_break_render(self):
        settings = auth_settings({"RENDER": "true", "RENDER_EXTERNAL_URL": "https://club.onrender.com",
                                  "PUBLIC_BASE_URL": "http://127.0.0.1:5000",
                                  "GOOGLE_REDIRECT_URI": "http://127.0.0.1:5000/auth/google/callback",
                                  "SESSION_COOKIE_SECURE": "false"})
        self.assertEqual(settings["GOOGLE_REDIRECT_URI"], "https://club.onrender.com/auth/google/callback")
        self.assertTrue(settings["SESSION_COOKIE_SECURE"])

    def test_dotenv_is_used_only_locally_and_environment_has_priority(self):
        with TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("GOOGLE_CLIENT_ID=local-test-client\nCLUB_MEMBERS=member@example.com\n", encoding="utf-8")
            local = runtime_environment({}, env_file)
            self.assertEqual(local["GOOGLE_CLIENT_ID"], "local-test-client")
            explicit = runtime_environment({"GOOGLE_CLIENT_ID": "explicit-test-client"}, env_file)
            self.assertEqual(explicit["GOOGLE_CLIENT_ID"], "explicit-test-client")
            hosted = runtime_environment({"RENDER": "true", "GOOGLE_CLIENT_ID": "render-test-client"}, env_file)
            self.assertEqual(hosted["GOOGLE_CLIENT_ID"], "render-test-client")
            self.assertNotIn("CLUB_MEMBERS", hosted)

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

    def test_production_bank_callback_uses_registered_path_in_both_environments(self):
        settings = auth_settings({"ENABLE_BANKING_CALLBACK_PATH":"/callback"})
        self.assertEqual(settings["ENABLE_BANKING_REDIRECT_URI"],"http://127.0.0.1:5000/callback")
        settings = auth_settings({"RENDER_EXTERNAL_URL":"https://lilla-kulturklubben.onrender.com",
                                  "ENABLE_BANKING_CALLBACK_PATH":"/callback"})
        self.assertEqual(settings["ENABLE_BANKING_REDIRECT_URI"],"https://lilla-kulturklubben.onrender.com/callback")

    def test_bank_callback_path_cannot_redirect_to_another_origin(self):
        with self.assertRaises(ValueError):
            auth_settings({"ENABLE_BANKING_CALLBACK_PATH":"https://evil.example/callback"})

    def test_invalid_public_addresses_fail_closed(self):
        for base in ("http://club.example", "https://club.example/path", "https://user@club.example",
                     "https://club.example?next=evil", "//club.example", "https://club.example#hash"):
            with self.subTest(base=base), self.assertRaises(ValueError):
                auth_settings({"PUBLIC_BASE_URL": base})
