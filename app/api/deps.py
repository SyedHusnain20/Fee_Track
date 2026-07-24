"""Auth dependencies: resolve the logged-in admin from the session cookie.

Step 6.
"""

from datetime import datetime
from typing import Optional

from fastapi import Cookie, Depends, HTTPException, status
from sqlmodel import Session

from app.core.database import get_session
from app.core.security import SESSION_COOKIE_NAME
from app.models.admin_session import AdminSession
from app.models.admin_user import AdminUser


def _redirect_to_login() -> HTTPException:
    """Raised instead of returned so it short-circuits the dependency chain.
    Sets both Location (for normal browser navigation) and HX-Redirect (so
    an HTMX request also does a full-page redirect instead of swapping the
    redirect body into a fragment) — worth knowing since your admin UI is
    HTMX-driven from Step 7 onward."""
    return HTTPException(
        status_code=status.HTTP_303_SEE_OTHER,
        headers={"Location": "/login", "HX-Redirect": "/login"},
    )


async def get_current_admin(
    session: Session = Depends(get_session),
    raabta_session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> AdminUser:
    """Resolve the session cookie into a live, active AdminUser.

    AdminUser is re-fetched fresh from the DB on every request — never
    cached on the session row — so a super-admin deactivating an account
    takes effect on that admin's very next request, not just their next
    login attempt.
    """
    if raabta_session is None:
        raise _redirect_to_login()

    admin_session = session.get(AdminSession, raabta_session)
    # Naive UTC comparison, matching datetime.utcnow() used everywhere else
    # in this codebase (see AdminSession/security.py comments).
    if admin_session is None or admin_session.expires_at < datetime.utcnow():
        raise _redirect_to_login()

    admin = session.get(AdminUser, admin_session.admin_id)
    if admin is None or not admin.is_active:
        # Deactivated or deleted admin: clear the now-dangling session row
        # too, rather than leaving it to expire on its own.
        session.delete(admin_session)
        session.commit()
        raise _redirect_to_login()

    return admin


async def require_super_admin(admin: AdminUser = Depends(get_current_admin)) -> AdminUser:
    if not admin.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super-admin access required.",
        )
    return admin
