"""Login / logout routes. Step 6.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.core.config import settings
from app.core.database import get_session
from app.core.security import (
    SESSION_COOKIE_NAME,
    generate_session_token,
    new_expiry,
    verify_password,
)
from app.models.admin_session import AdminSession
from app.models.admin_user import AdminUser
from app.api.deps import get_current_admin

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory="app/templates")

# Derived from your existing ENVIRONMENT setting (development|production) —
# secure cookies are skipped locally (plain HTTP) and enforced everywhere
# else. This is why COOKIE_SECURE=False locally isn't something you need to
# remember to flip by hand.
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
    admin = session.exec(
        select(AdminUser).where(AdminUser.email == email.strip().lower())
    ).first()

    # Runs even when `admin` is None (verify_password falls back to a dummy
    # hash) so failed logins take constant time regardless of whether the
    # email exists — see security.py for why.
    password_ok = verify_password(password, admin.password_hash if admin else None)

    if not admin or not admin.is_active or not password_ok:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid email or password."},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

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

    # TODO: change "/dashboard" to wherever Step 7's admin home route lands.
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
