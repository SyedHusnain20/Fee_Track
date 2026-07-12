"""Minimal admin dashboard landing page.

This is what Step 6's login POST redirects to — it was a deliberate 404
until now. This fills it in with just enough to be a real landing page; it
gains admin-relevant summary widgets (fee cycles due, attendance today,
etc.) as Steps 7-10 land.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlmodel import Session, select

from app.api.deps import get_current_admin
from app.core.database import get_session
from app.models.admin_user import AdminUser
from app.models.student import Student
from app.models.teacher import Teacher

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    active_students = session.exec(
        select(func.count()).select_from(Student).where(Student.is_active.is_(True))
    ).one()
    active_teachers = session.exec(
        select(func.count()).select_from(Teacher).where(Teacher.is_active.is_(True))
    ).one()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "admin": admin,
            "active_students": active_students,
            "active_teachers": active_teachers,
        },
    )
