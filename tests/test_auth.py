"""Unit tests for SunkGuard OTP Authentication, Database, and Rate Limiting."""

import os
import tempfile
import time
import unittest

from core.auth import AuthManager
from core.auth_db import AuthDatabase
from core.email_service import EmailService


class TestAuthSystem(unittest.TestCase):
    def setUp(self):
        # Use an isolated temporary database for each test
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_auth.db")
        self.db = AuthDatabase(db_path=self.db_path)
        self.email_service = EmailService(smtp_host="")  # force dev mode
        self.auth = AuthManager(db=self.db, email_service=self.email_service)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_request_otp_success(self):
        res = self.auth.request_otp("alice@example.com")
        self.assertTrue(res["success"])
        self.assertEqual(res["email"], "alice@example.com")
        self.assertEqual(len(res["dev_otp"]), 6)
        self.assertTrue(res["dev_otp"].isdigit())

        # Verify DB stored hashed OTP, not plaintext
        record = self.db.get_otp("alice@example.com")
        self.assertIsNotNone(record)
        self.assertNotEqual(record.otp_hash, res["dev_otp"])
        self.assertEqual(record.attempts, 0)

    def test_invalid_email_rejection(self):
        res = self.auth.request_otp("invalid-email-string")
        self.assertFalse(res["success"])
        self.assertEqual(res["error"], "INVALID_EMAIL")

    def test_resend_cooldown_rate_limit(self):
        res1 = self.auth.request_otp("bob@example.com")
        self.assertTrue(res1["success"])

        # Immediate second request should be rate-limited
        res2 = self.auth.request_otp("bob@example.com")
        self.assertFalse(res2["success"])
        self.assertEqual(res2["error"], "RATE_LIMITED")
        self.assertIn("retry_after_seconds", res2)

    def test_verify_otp_wrong_code_and_lockout(self):
        req = self.auth.request_otp("carol@example.com")
        valid_otp = req["dev_otp"]
        wrong_otp = "000000" if valid_otp != "000000" else "111111"

        # Attempt 1: wrong code
        res1 = self.auth.verify_otp("carol@example.com", wrong_otp)
        self.assertFalse(res1["success"])
        self.assertEqual(res1["remaining_attempts"], 2)

        # Attempt 2: wrong code
        res2 = self.auth.verify_otp("carol@example.com", wrong_otp)
        self.assertFalse(res2["success"])
        self.assertEqual(res2["remaining_attempts"], 1)

        # Attempt 3: wrong code -> code invalidated
        res3 = self.auth.verify_otp("carol@example.com", wrong_otp)
        self.assertFalse(res3["success"])
        self.assertEqual(res3["remaining_attempts"], 0)
        self.assertIn("locked", res3["message"].lower())

        # Attempt 4 with valid code should now fail because it was purged
        res4 = self.auth.verify_otp("carol@example.com", valid_otp)
        self.assertFalse(res4["success"])
        self.assertEqual(res4["error"], "NO_ACTIVE_OTP")

    def test_verify_otp_success_and_session_lifecycle(self):
        req = self.auth.request_otp("engineer@sunkguard.ai")
        valid_otp = req["dev_otp"]

        # Verify
        res = self.auth.verify_otp("engineer@sunkguard.ai", valid_otp)
        self.assertTrue(res["success"])
        self.assertIn("token", res)
        self.assertTrue(res["token"].startswith("sg_"))
        self.assertEqual(res["user"]["email"], "engineer@sunkguard.ai")

        # Validate session
        profile = self.auth.validate_session(f"Bearer {res['token']}")
        self.assertIsNotNone(profile)
        self.assertEqual(profile["email"], "engineer@sunkguard.ai")

        # Revoke session (logout)
        revoked = self.auth.revoke_session(f"Bearer {res['token']}")
        self.assertTrue(revoked)

        # Validating revoked session should fail
        profile_after = self.auth.validate_session(f"Bearer {res['token']}")
        self.assertIsNone(profile_after)


if __name__ == "__main__":
    unittest.main()
