"""Persistent SQLite Database layer for SunkGuard Authentication.

Manages tables:
1. users: registered user accounts, roles, and profiles.
2. otp_codes: hashed OTP tokens, salts, attempt counts, and expiration.
3. sessions: active and revoked session bearer tokens.
"""

from dataclasses import dataclass
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional


@dataclass
class UserRecord:
    id: str
    email: str
    name: str
    role: str
    created_at: float
    last_login_at: float


@dataclass
class OTPRecord:
    email: str
    otp_hash: str
    salt: str
    attempts: int
    resend_cooldown_until: float
    expires_at: float
    created_at: float


@dataclass
class SessionRecord:
    token_hash: str
    email: str
    created_at: float
    expires_at: float
    is_revoked: bool


class AuthDatabase:
    """Thread-safe SQLite database manager for user authentication and sessions."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path:
            self.db_path = Path(db_path)
        else:
            self.db_path = Path(__file__).resolve().parent.parent / "data" / "auth.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS users (
                            id TEXT PRIMARY KEY,
                            email TEXT UNIQUE NOT NULL,
                            name TEXT NOT NULL,
                            role TEXT DEFAULT 'Engineer',
                            created_at REAL NOT NULL,
                            last_login_at REAL NOT NULL
                        );
                    """)
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS otp_codes (
                            email TEXT PRIMARY KEY,
                            otp_hash TEXT NOT NULL,
                            salt TEXT NOT NULL,
                            attempts INTEGER DEFAULT 0,
                            resend_cooldown_until REAL NOT NULL,
                            expires_at REAL NOT NULL,
                            created_at REAL NOT NULL
                        );
                    """)
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS sessions (
                            token_hash TEXT PRIMARY KEY,
                            email TEXT NOT NULL,
                            created_at REAL NOT NULL,
                            expires_at REAL NOT NULL,
                            is_revoked INTEGER DEFAULT 0,
                            FOREIGN KEY (email) REFERENCES users(email)
                        );
                    """)
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_email ON sessions(email);")
            finally:
                conn.close()

    # -------------------------------------------------------------------------
    # OTP Management
    # -------------------------------------------------------------------------

    def store_otp(
        self,
        email: str,
        otp_hash: str,
        salt: str,
        expires_at: float,
        resend_cooldown_until: float,
    ) -> None:
        now = time.time()
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("""
                        INSERT INTO otp_codes (email, otp_hash, salt, attempts, resend_cooldown_until, expires_at, created_at)
                        VALUES (?, ?, ?, 0, ?, ?, ?)
                        ON CONFLICT(email) DO UPDATE SET
                            otp_hash = excluded.otp_hash,
                            salt = excluded.salt,
                            attempts = 0,
                            resend_cooldown_until = excluded.resend_cooldown_until,
                            expires_at = excluded.expires_at,
                            created_at = excluded.created_at;
                    """, (email.lower(), otp_hash, salt, resend_cooldown_until, expires_at, now))
            finally:
                conn.close()

    def get_otp(self, email: str) -> Optional[OTPRecord]:
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.execute("SELECT * FROM otp_codes WHERE email = ?;", (email.lower(),))
                row = cur.fetchone()
                if not row:
                    return None
                return OTPRecord(
                    email=row["email"],
                    otp_hash=row["otp_hash"],
                    salt=row["salt"],
                    attempts=row["attempts"],
                    resend_cooldown_until=row["resend_cooldown_until"],
                    expires_at=row["expires_at"],
                    created_at=row["created_at"],
                )
            finally:
                conn.close()

    def increment_attempts(self, email: str) -> int:
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("UPDATE otp_codes SET attempts = attempts + 1 WHERE email = ?;", (email.lower(),))
                cur = conn.execute("SELECT attempts FROM otp_codes WHERE email = ?;", (email.lower(),))
                row = cur.fetchone()
                return row["attempts"] if row else 0
            finally:
                conn.close()

    def delete_otp(self, email: str) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("DELETE FROM otp_codes WHERE email = ?;", (email.lower(),))
            finally:
                conn.close()

    # -------------------------------------------------------------------------
    # User Management
    # -------------------------------------------------------------------------

    def create_or_get_user(self, email: str, name: Optional[str] = None) -> UserRecord:
        email = email.lower()
        now = time.time()
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.execute("SELECT * FROM users WHERE email = ?;", (email,))
                row = cur.fetchone()
                if row:
                    with conn:
                        conn.execute("UPDATE users SET last_login_at = ? WHERE email = ?;", (now, email))
                    return UserRecord(
                        id=row["id"],
                        email=row["email"],
                        name=row["name"],
                        role=row["role"],
                        created_at=row["created_at"],
                        last_login_at=now,
                    )

                # Create new user
                user_id = f"usr_{int(now * 1000)}"
                display_name = name or email.split("@")[0].capitalize()
                role = "Lead Architect" if "deepmind" in email or "admin" in email else "Control Plane Engineer"
                with conn:
                    conn.execute("""
                        INSERT INTO users (id, email, name, role, created_at, last_login_at)
                        VALUES (?, ?, ?, ?, ?, ?);
                    """, (user_id, email, display_name, role, now, now))

                return UserRecord(
                    id=user_id,
                    email=email,
                    name=display_name,
                    role=role,
                    created_at=now,
                    last_login_at=now,
                )
            finally:
                conn.close()

    def get_user_by_email(self, email: str) -> Optional[UserRecord]:
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.execute("SELECT * FROM users WHERE email = ?;", (email.lower(),))
                row = cur.fetchone()
                if not row:
                    return None
                return UserRecord(
                    id=row["id"],
                    email=row["email"],
                    name=row["name"],
                    role=row["role"],
                    created_at=row["created_at"],
                    last_login_at=row["last_login_at"],
                )
            finally:
                conn.close()

    # -------------------------------------------------------------------------
    # Session Management
    # -------------------------------------------------------------------------

    def create_session(self, token_hash: str, email: str, expires_at: float) -> None:
        now = time.time()
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("""
                        INSERT INTO sessions (token_hash, email, created_at, expires_at, is_revoked)
                        VALUES (?, ?, ?, ?, 0);
                    """, (token_hash, email.lower(), now, expires_at))
            finally:
                conn.close()

    def get_session(self, token_hash: str) -> Optional[SessionRecord]:
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.execute("SELECT * FROM sessions WHERE token_hash = ? AND is_revoked = 0;", (token_hash,))
                row = cur.fetchone()
                if not row:
                    return None
                return SessionRecord(
                    token_hash=row["token_hash"],
                    email=row["email"],
                    created_at=row["created_at"],
                    expires_at=row["expires_at"],
                    is_revoked=bool(row["is_revoked"]),
                )
            finally:
                conn.close()

    def revoke_session(self, token_hash: str) -> bool:
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    cur = conn.execute("UPDATE sessions SET is_revoked = 1 WHERE token_hash = ?;", (token_hash,))
                    return cur.rowcount > 0
            finally:
                conn.close()

    def clear(self) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("DELETE FROM otp_codes;")
                    conn.execute("DELETE FROM sessions;")
                    conn.execute("DELETE FROM users;")
            finally:
                conn.close()


# Global singleton instance
AUTH_DB = AuthDatabase()
