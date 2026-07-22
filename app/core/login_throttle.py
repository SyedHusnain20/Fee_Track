"""In-memory login rate limiting — Step 13. 5 failed attempts -> 15 minute
lockout, keyed by normalized email (not IP): protects a specific admin
account from being brute-forced, rather than defending a shared network
egress point. Resets to zero on container restart — an accepted tradeoff
for this single-instance, single-VPS deployment, where Redis would be new
operational weight for no real scaling benefit (see rate-limiting
discussion earlier in this conversation).
"""
import threading
from datetime import datetime, timedelta
from typing import Optional

MAX_ATTEMPTS = 5
LOCKOUT_DURATION = timedelta(minutes=15)

_lock = threading.Lock()
_attempts: dict[str, dict] = {}  # normalized email -> {"count": int, "locked_until": datetime | None}


def _key(email: str) -> str:
    return email.strip().lower()


def get_lockout_remaining(email: str) -> Optional[timedelta]:
    """Returns remaining lockout duration if currently locked out, else None."""
    with _lock:
        record = _attempts.get(_key(email))
        if not record or not record.get("locked_until"):
            return None
        remaining = record["locked_until"] - datetime.utcnow()
        if remaining <= timedelta(0):
            del _attempts[_key(email)]  # lockout expired naturally
            return None
        return remaining


def register_failure(email: str) -> None:
    with _lock:
        key = _key(email)
        record = _attempts.setdefault(key, {"count": 0, "locked_until": None})
        record["count"] += 1
        if record["count"] >= MAX_ATTEMPTS:
            record["locked_until"] = datetime.utcnow() + LOCKOUT_DURATION
            record["count"] = 0


def register_success(email: str) -> None:
    with _lock:
        _attempts.pop(_key(email), None)