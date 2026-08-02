"""In-memory signup rate limiting.

Unlike login_throttle.py (keyed by email, because the risk there is
brute-forcing one specific admin's password), this is keyed by client IP:
a signup submission needs no prior knowledge of any account, so the risk
here is one source flooding the Admin Requests queue (Phase 4) with junk
pending accounts. Email-level duplicate protection is handled separately
in auth.signup_submit via the existing-email check, which already stops
the same address from queuing more than one request.

Same in-memory, single-instance tradeoff as login_throttle.py: resets on
container restart, no Redis — acceptable for this single-VPS deployment.
"""

import threading
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Request

MAX_ATTEMPTS = 5
LOCKOUT_DURATION = timedelta(minutes=30)

_lock = threading.Lock()
_attempts: dict[
    str, dict
] = {}  # client IP -> {"count": int, "locked_until": datetime | None}


def get_client_ip(request: Request) -> str:
    """Prefer the X-Real-IP header nginx sets (see nginx/nginx.conf) over
    request.client.host, since uvicorn isn't run with --proxy-headers —
    without this, every request arrives via the nginx container and
    request.client.host would be the same internal IP for every visitor,
    turning this into a single shared bucket instead of a per-visitor one.
    Falls back to request.client.host for local dev without nginx in
    front, and to a fixed string if that's unavailable too (e.g. tests)."""
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def get_lockout_remaining(ip: str) -> Optional[timedelta]:
    """Returns remaining lockout duration if currently locked out, else None."""
    with _lock:
        record = _attempts.get(ip)
        if not record or not record.get("locked_until"):
            return None
        remaining = record["locked_until"] - datetime.utcnow()
        if remaining <= timedelta(0):
            del _attempts[ip]  # lockout expired naturally
            return None
        return remaining


def register_attempt(ip: str) -> None:
    """Call once per /signup submission, success or failure alike — unlike
    login throttling, a spam risk doesn't get a free pass just because the
    submitted data happened to be well-formed."""
    with _lock:
        record = _attempts.setdefault(ip, {"count": 0, "locked_until": None})
        record["count"] += 1
        if record["count"] >= MAX_ATTEMPTS:
            record["locked_until"] = datetime.utcnow() + LOCKOUT_DURATION
            record["count"] = 0