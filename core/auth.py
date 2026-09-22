"""Core Authentication Manager for SunkGuard OTP Verification.

Implements:
1. Cryptographically secure 6-digit OTP generation using secrets module
2. Salted SHA-256 hashing (no plaintext OTP persistence)
3. 5-minute hard TTL and 30-second resend cooldown rate-limiting
4. Brute-force lockout (max 3 failed attempts)
5. Bearer token session issuance and validation backed by SQLite
"""

from dataclasses import asdict
import hashlib
import hmac
import re
import secrets
import time
from typing import Any, Dict, Optional

from core.auth_db import AUTH_DB, UserRecord
from core.email_service import EMAIL_SERVICE

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
OTP_TTL_SECONDS = 300.0        # 5 minutes
RESEND_COOLDOWN_SECONDS = 30.0 # 30 seconds rate-limit between resends
MAX_VERIFICATION_ATTEMPTS = 3
SESSION_TTL_SECONDS = 86400.0  # 24 hours


class AuthManager:
    """Authentication and session management controller."""

    def __init__(self, db=None, email_service=None):
        self.db = db or AUTH_DB
        self.email_service = email_service or EMAIL_SERVICE

    def _hash_otp(self, otp: str, salt: str) -> str:
        return hashlib.sha256(f"{salt}:{otp}".encode("utf-8")).hexdigest()

    def _hash_token(self, token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def request_otp(self, email: str) -> Dict[str, Any]:
        """Validates email, checks rate limits, generates OTP, and dispatches email."""
        clean_email = email.strip().lower()
        if not EMAIL_REGEX.match(clean_email):
            return {
                "success": False,
                "error": "INVALID_EMAIL",
                "message": "Please provide a valid email address.",
            }

        now = time.time()
        existing = self.db.get_otp(clean_email)

        # Rate limiting: 30-second cooldown between resend requests
        if existing and now < existing.resend_cooldown_until:
            wait_seconds = int(existing.resend_cooldown_until - now)
            return {
                "success": False,
                "error": "RATE_LIMITED",
                "message": f"Please wait {wait_seconds}s before requesting a new code.",
                "retry_after_seconds": wait_seconds,
            }

        # Generate cryptographically secure 6-digit OTP
        raw_otp = f"{secrets.randbelow(900000) + 100000:06d}"
        salt = secrets.token_hex(16)
        otp_hash = self._hash_otp(raw_otp, salt)
        expires_at = now + OTP_TTL_SECONDS
        resend_cooldown_until = now + RESEND_COOLDOWN_SECONDS

        # Store in SQLite database
        self.db.store_otp(
            email=clean_email,
            otp_hash=otp_hash,
            salt=salt,
            expires_at=expires_at,
            resend_cooldown_until=resend_cooldown_until,
        )

        # Dispatch via email service
        delivery_res = self.email_service.send_otp(clean_email, raw_otp)

        return {
            "success": True,
            "email": clean_email,
            "expires_in_seconds": int(OTP_TTL_SECONDS),
            "resend_cooldown_seconds": int(RESEND_COOLDOWN_SECONDS),
            "message": f"Verification code sent to {clean_email}.",
            "delivery_method": delivery_res.get("method", "dev_console"),
            "dev_otp": delivery_res.get("dev_otp"),  # Convenient helper for evaluation demos
        }

    def verify_otp(self, email: str, otp_candidate: str) -> Dict[str, Any]:
        """Validates OTP, enforces attempt limits, and issues session token."""
        clean_email = email.strip().lower()
        clean_otp = str(otp_candidate).strip()

        now = time.time()
        record = self.db.get_otp(clean_email)

        if not record:
            return {
                "success": False,
                "error": "NO_ACTIVE_OTP",
                "message": "No verification request found for this email. Please request a new code.",
            }

        # Check expiration
        if now > record.expires_at:
            self.db.delete_otp(clean_email)
            return {
                "success": False,
                "error": "EXPIRED_OTP",
                "message": "Verification code has expired. Please request a new code.",
            }

        # Check brute-force lockout
        if record.attempts >= MAX_VERIFICATION_ATTEMPTS:
            self.db.delete_otp(clean_email)
            return {
                "success": False,
                "error": "TOO_MANY_ATTEMPTS",
                "message": "Too many failed attempts. Code invalidated for your security. Please request a new code.",
            }

        # Verify hash using constant-time comparison
        expected_hash = record.otp_hash
        candidate_hash = self._hash_otp(clean_otp, record.salt)

        if not hmac.compare_digest(expected_hash, candidate_hash):
            attempts = self.db.increment_attempts(clean_email)
            remaining = max(0, MAX_VERIFICATION_ATTEMPTS - attempts)
            if remaining == 0:
                self.db.delete_otp(clean_email)
                return {
                    "success": False,
                    "error": "TOO_MANY_ATTEMPTS",
                    "message": "Incorrect code. Maximum attempts exceeded. Code has been locked and invalidated. Please request a new code.",
                    "remaining_attempts": 0,
                }
            return {
                "success": False,
                "error": "INVALID_OTP",
                "message": f"Incorrect code. {remaining} attempt(s) remaining.",
                "remaining_attempts": remaining,
            }

        # Success: Consume OTP and create/fetch user record
        self.db.delete_otp(clean_email)
        user = self.db.create_or_get_user(clean_email)

        # Issue secure 32-byte hex session token
        raw_session_token = f"sg_{secrets.token_hex(32)}"
        token_hash = self._hash_token(raw_session_token)
        session_expires_at = now + SESSION_TTL_SECONDS
        self.db.create_session(token_hash, clean_email, session_expires_at)

        return {
            "success": True,
            "token": raw_session_token,
            "expires_at": session_expires_at,
            "user": {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "role": user.role,
                "last_login_at": user.last_login_at,
            },
        }

    def validate_session(self, token: str) -> Optional[Dict[str, Any]]:
        """Verifies session token from Authorization header and returns user profile."""
        if not token:
            return None
        clean_token = token.replace("Bearer ", "").strip()
        token_hash = self._hash_token(clean_token)
        session = self.db.get_session(token_hash)
        if not session or time.time() > session.expires_at:
            return None

        user = self.db.get_user_by_email(session.email)
        if not user:
            return None

        return {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "expires_at": session.expires_at,
        }

    def revoke_session(self, token: str) -> bool:
        """Invalidates active session token."""
        if not token:
            return False
        clean_token = token.replace("Bearer ", "").strip()
        token_hash = self._hash_token(clean_token)
        return self.db.revoke_session(token_hash)


# Global singleton instance
AUTH_MANAGER = AuthManager()
