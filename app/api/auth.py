"""Login / logout routes. Step 6, rate-limiting added in Step 13.

Self-serve admin signup added in Phase 2 of the approval-workflow feature:
GET/POST /signup collects name/email/password, creates an AdminUser with
is_approved=False, and redirects to a static "awaiting approval" page.
Nothing here grants access by itself — login_submit below (Phase 3) is
what actually blocks a pending admin from getting a session, and Admin
Requests (Phase 4) is what flips is_approved to True.

Phase 5 hardens signup: per-IP rate limiting (app.core.signup_throttle,
separate from login_throttle's per-email limiting — see that module's
docstring for why), and an audit-log entry on every successful signup.
The duplicate-signup guard already existed as of Phase 2 (the existing-
email check below) and needed no changes here.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.api.deps import get_current_admin
from app.core.config import settings
from app.core.database import get_session
from app.core.login_throttle import get_lockout_remaining, register_failure, register_success
from app.core.security import (
    SESSION_COOKIE_NAME,
    generate_session_token,
    hash_password,
    new_expiry,
    verify_password,
)
from app.core.signup_throttle import get_client_ip
from app.core.signup_throttle import get_lockout_remaining as get_signup_lockout_remaining
from app.core.signup_throttle import register_attempt as register_signup_attempt
from app.models.admin_session import AdminSession
from app.models.admin_user import AdminUser
from app.models.enums import AuditAction
from app.services.audit import write_audit_log

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory="app/templates")

COOKIE_SECURE = settings.ENVIRONMENT == "production"


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session),
):
    lockout_remaining = get_lockout_remaining(email)
    if lockout_remaining is not None:
        minutes = max(1, int(lockout_remaining.total_seconds() // 60) + 1)
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": f"Too many failed attempts. Try again in {minutes} minute"
                f"{'s' if minutes != 1 else ''}.",
            },
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    admin = session.exec(select(AdminUser).where(AdminUser.email == email.strip().lower())).first()

    password_ok = verify_password(password, admin.password_hash if admin else None)

    if not admin or not admin.is_active or not password_ok:
        register_failure(email)
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid email or password."},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    if not admin.is_approved:
        # Credentials are correct, so this isn't a failed login attempt for
        # throttling purposes — reset the counter same as a normal success —
        # but no session is issued until a super admin approves the request
        # from Admin Requests (Phase 4). Message is deliberately specific
        # here: unlike the generic "invalid email or password" above, the
        # person already proved they own this account by entering the
        # correct password, so confirming pending status doesn't leak
        # anything they don't already know.
        register_success(email)
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Your account is awaiting super-admin approval. "
                "You'll be able to sign in once it's approved.",
            },
            status_code=status.HTTP_403_FORBIDDEN,
        )

    register_success(email)

    token = generate_session_token()
    admin_session = AdminSession(
        token=token,
        admin_id=admin.id,
        created_at=datetime.utcnow(),
        expires_at=new_expiry(),
        user_agent=request.headers.get("user-agent", "")[:255],
    )
    session.add(admin_session)
    session.commit()

    redirect = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    redirect.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        max_age=12 * 60 * 60,
        path="/",
    )
    return redirect


@router.post("/logout")
async def logout(
    request: Request,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        admin_session = session.get(AdminSession, token)
        if admin_session:
            session.delete(admin_session)
            session.commit()

    redirect = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    redirect.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return redirect


@router.get("/signup", response_class=HTMLResponse)
async def signup_form(request: Request):
    return templates.TemplateResponse(
        "signup.html",
        {"request": request, "error": None, "name": "", "email": ""},
    )


@router.post("/signup", response_class=HTMLResponse)
async def signup_submit(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    session: Session = Depends(get_session),
):
    client_ip = get_client_ip(request)
    lockout_remaining = get_signup_lockout_remaining(client_ip)
    if lockout_remaining is not None:
        minutes = max(1, int(lockout_remaining.total_seconds() // 60) + 1)
        return templates.TemplateResponse(
            "signup.html",
            {
                "request": request,
                "error": f"Too many requests from this connection. Try again in "
                f"{minutes} minute{'s' if minutes != 1 else ''}.",
                "name": "",
                "email": "",
            },
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    # Counted regardless of whether the submission turns out valid — a
    # spam risk doesn't get a free pass just because the data was
    # well-formed (see signup_throttle.register_attempt docstring).
    register_signup_attempt(client_ip)

    name = name.strip()
    email = email.strip().lower()

    def _rerender(message: str, status_code: int) -> HTMLResponse:
        return templates.TemplateResponse(
            "signup.html",
            {"request": request, "error": message, "name": name, "email": email},
            status_code=status_code,
        )

    if not name:
        return _rerender("Enter your full name.", status.HTTP_400_BAD_REQUEST)

    if password != confirm_password:
        return _rerender("Passwords do not match.", status.HTTP_400_BAD_REQUEST)

    if len(password) < 8:
        return _rerender(
            "Password must be at least 8 characters.", status.HTTP_400_BAD_REQUEST
        )

    # Also the duplicate-signup guard: one email can have at most one
    # AdminUser row at a time (unique index on AdminUser.email), so this
    # blocks a second request from an email that's already pending or
    # already approved. A previously rejected email is free to sign up
    # again since rejection hard-deletes the row (Phase 4).
    existing = session.exec(select(AdminUser).where(AdminUser.email == email)).first()
    if existing:
        # Deliberately specific here (unlike login's generic "invalid email
        # or password") — this is a signup form, not an auth check, so
        # confirming the email is already registered doesn't expose
        # anything an attacker couldn't already infer by trying to sign up
        # with it themselves, and it saves a genuine admin from wondering
        # why their request never shows up.
        return _rerender(
            "An account with this email already exists.", status.HTTP_409_CONFLICT
        )

    admin = AdminUser(
        name=name,
        email=email,
        password_hash=hash_password(password),
        is_active=True,
        is_super_admin=False,
        is_approved=False,
    )
    session.add(admin)
    # Flush (not just commit) so admin.id exists for the audit-log write
    # below — same pattern as app.api.enrollments's create route.
    session.flush()

    write_audit_log(
        session,
        # No logged-in admin exists yet to be the actor — this is a
        # self-service action, so the new admin is recorded as acting on
        # their own behalf. Approve/reject in admin_accounts.py, by
        # contrast, log the super admin who took the action.
        admin_id=admin.id,
        action=AuditAction.CREATE,
        entity_type="AdminUser",
        entity_id=admin.id,
        before_value=None,
        after_value={
            "name": admin.name,
            "email": admin.email,
            "is_approved": admin.is_approved,
        },
    )
    session.commit()

    return RedirectResponse(url="/signup/pending", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/signup/pending", response_class=HTMLResponse)
async def signup_pending(request: Request):
    return templates.TemplateResponse("signup_pending.html", {"request": request})