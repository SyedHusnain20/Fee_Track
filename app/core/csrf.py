"""CSRF protection — Step 13. A single app-level dependency (registered
once in main.py's FastAPI(dependencies=[...])) that:
  1. Computes a per-session CSRF token and stores it on request.state, so
     every Jinja2 template can reference {{ request.state.csrf_token }}
     directly — no per-route-file wiring, since every route already passes
     {"request": request, ...} into its template context.
  2. Verifies the submitted csrf_token form field on state-changing
     requests (POST/PUT/PATCH/DELETE) from a logged-in admin session.

Deliberately skips /kiosk entirely — unauthenticated by design (Section
3), no session to protect. Also skips any request with no session cookie
at all (e.g. POST /login itself — no prior session exists to hijack
before login succeeds; login-CSRF is a separate, lower-severity concern
not in scope here).

Verified empirically against this project's exact pinned versions
(fastapi==0.115.6 / starlette==0.41.3) that reading request.form() here
does NOT break the route handler's own Form(...) parameter parsing —
dependencies and the route handler share the same Request instance, and
Starlette caches the parsed form on it.
"""
from fastapi import HTTPException, Request, status
from itsdangerous import BadSignature, URLSafeSerializer

from app.core.config import settings

from app.core.security import SESSION_COOKIE_NAME

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


async def csrf_protect(request: Request) -> None:
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    request.state.csrf_token = generate_csrf_token(session_token) if session_token else ""

    if request.method not in _UNSAFE_METHODS:
        return
    if request.url.path.startswith("/kiosk"):
        return
    if not session_token:
        return  # No session to protect (e.g. POST /login before a session exists)

    form = await request.form()
    submitted = form.get("csrf_token")
    if not submitted or not verify_csrf_token(str(submitted), session_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your session token is invalid or expired. Please refresh the page and try again.",
        )

_csrf_serializer = URLSafeSerializer(settings.SECRET_KEY, salt="csrf-token")


def generate_csrf_token(session_token: str) -> str:
    """Deterministic per-session token: the same session_token always
    produces the same csrf_token, so nothing needs to be stored server-side
    — verification just re-derives and compares against the live session
    cookie."""
    return _csrf_serializer.dumps(session_token)


def verify_csrf_token(submitted_token: str, session_token: str) -> bool:
    try:
        decoded = _csrf_serializer.loads(submitted_token)
    except BadSignature:
        return False
    return decoded == session_token