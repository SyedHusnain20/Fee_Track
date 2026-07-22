"""Login / logout routes. Step 6, rate-limiting added in Step 13.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.core.config import settings
from app.core.database import get_session
from app.core.login_throttle import get_lockout_remaining, register_failure, register_success
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
                "error": f"Too many failed attempts. Try again in {minutes} minute{'s' if minutes != 1 else ''}.",
            },
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    admin = session.exec(
        select(AdminUser).where(AdminUser.email == email.strip().lower())
    ).first()

    password_ok = verify_password(password, admin.password_hash if admin else None)

    if not admin or not admin.is_active or not password_ok:
        register_failure(email)
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid email or password."},
            status_code=status.HTTP_401_UNAUTHORIZED,
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