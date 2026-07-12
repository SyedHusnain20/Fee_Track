"""Password hashing and session-token utilities for admin authentication.

Step 6.
"""
import secrets
from datetime import datetime, timedelta

from passlib.context import CryptContext

# Argon2id is the current OWASP-recommended default: memory-hard, and it
# sidesteps the bcrypt-72-byte-truncation / passlib-bcrypt version-pinning
# issues that commonly bite people in production.
# Requires: pip install "passlib[argon2]"
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

SESSION_COOKIE_NAME = "raabta_session"
SESSION_LIFETIME = timedelta(hours=12)

# A precomputed argon2 hash of a random string. Used as a stand-in when
# verifying a login attempt against an email that doesn't exist, so that a
# failed login takes the same amount of time whether the email is real or
# not. Without this, response timing alone can be used to enumerate valid
# admin emails.
_DUMMY_HASH = pwd_context.hash(secrets.token_urlsafe(32))


def hash_password(plain_password: str) -> str:
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, password_hash: str | None) -> bool:
    """Verify a password. Pass password_hash=None for a timing-safe check
    against a non-existent user (see _DUMMY_HASH above)."""
    return pwd_context.verify(plain_password, password_hash or _DUMMY_HASH)


def generate_session_token() -> str:
    # 32 bytes -> 43-char urlsafe token. Used directly as the AdminSession
    # primary key, so it also needs to be unguessable, not just unique.
    return secrets.token_urlsafe(32)


def new_expiry() -> datetime:
    # Naive UTC, matching datetime.utcnow() used throughout your other
    # models (AdminUser.created_at, AuditLog.timestamp, etc.) — mixing naive
    # and timezone-aware datetimes raises a TypeError the first time they're
    # compared, so this stays consistent with the rest of the codebase
    # rather than "more correct" in isolation.
    return datetime.utcnow() + SESSION_LIFETIME
