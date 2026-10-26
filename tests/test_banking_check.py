from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from banking_check import BankingCheckError, authorization, check_sandbox


class BankingCheckTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        key_path = Path(self.directory.name) / "test.pem"
        key_path.write_bytes(self.key.private_bytes(serialization.Encoding.PEM,
                                                   serialization.PrivateFormat.PKCS8,
                                                   serialization.NoEncryption()))
        self.config = {"ENABLE_BANKING_APPLICATION_ID": str(uuid4()),
                       "ENABLE_BANKING_PRIVATE_KEY_PATH": str(key_path)}

    def test_token_is_signed_with_correct_claims_and_application_id(self):
        token = authorization(self.config)["Authorization"].removeprefix("Bearer ")
        claims = jwt.decode(token, self.key.public_key(), algorithms=["RS256"],
                            issuer="enablebanking.com", audience="api.enablebanking.com")
        self.assertEqual(claims["exp"] - claims["iat"], 3600)
        self.assertEqual(jwt.get_unverified_header(token)["kid"], self.config["ENABLE_BANKING_APPLICATION_ID"])

    def test_missing_settings_fail_before_network(self):
        with patch("banking_check.requests.get") as get:
            with self.assertRaises(BankingCheckError):
                check_sandbox({})
            get.assert_not_called()

    def test_live_application_stops_before_bank_directory_request(self):
        response = Mock(status_code=200)
        response.json.return_value = {"environment": "PRODUCTION", "active": True}
        with patch("banking_check.requests.get", return_value=response) as get:
            with self.assertRaises(BankingCheckError):
                check_sandbox(self.config)
            self.assertEqual(get.call_count, 1)

    def test_sandbox_only_reads_application_and_swedish_bank_directory(self):
        application = Mock(status_code=200)
        application.json.return_value = {"environment": "SANDBOX", "active": True}
        banks = Mock(status_code=200)
        banks.json.return_value = {"aspsps": [{"name": "Test bank", "country": "SE"}]}
        with patch("banking_check.requests.get", side_effect=[application, banks]) as get:
            self.assertEqual(check_sandbox(self.config), ["Test bank"])
            self.assertEqual(get.call_args_list[0].args[0], "https://api.enablebanking.com/application")
            self.assertEqual(get.call_args_list[1].kwargs["params"], {"country": "SE"})
            self.assertFalse(get.call_args_list[1].kwargs["allow_redirects"])

    def test_api_failure_does_not_echo_response_or_credentials(self):
        response = Mock(status_code=401, text="sensitive response")
        with patch("banking_check.requests.get", return_value=response):
            with self.assertRaises(BankingCheckError) as error:
                check_sandbox(self.config)
        self.assertIn("401", str(error.exception))
        self.assertNotIn("sensitive response", str(error.exception))
