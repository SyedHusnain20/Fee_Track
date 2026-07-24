"""Admin dashboard landing page.

This is what Step 6's login POST redirects to. School vs Academy student
counts use the same student-has-an-active-enrollment-in-this-category-set
pattern as /students' filters (app/api/students.py) — verified there to
correctly count a student enrolled in both groups toward both counts,
without double-counting rows, since these are COUNT queries against
Student with an IN-subquery filter, not a join.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlmodel import Session, select

from app.api.deps import get_current_admin
from app.core.database import get_session
from app.models.admin_user import AdminUser
from app.models.enrollment import Enrollment
from app.models.enums import EnrollmentStatus, FeeCategory
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
    school_enrolled_ids = select(Enrollment.student_id).where(
        Enrollment.category == FeeCategory.SCHOOL,
        Enrollment.status == EnrollmentStatus.ACTIVE,
    )
    active_school_students = session.exec(
        select(func.count())
        .select_from(Student)
        .where(Student.is_active.is_(True), Student.id.in_(school_enrolled_ids))
    ).one()

    academy_enrolled_ids = select(Enrollment.student_id).where(
        Enrollment.category.in_([FeeCategory.COACHING, FeeCategory.ENGLISH, FeeCategory.COMPUTER]),
        Enrollment.status == EnrollmentStatus.ACTIVE,
    )
    active_academy_students = session.exec(
        select(func.count())
        .select_from(Student)
        .where(Student.is_active.is_(True), Student.id.in_(academy_enrolled_ids))
    ).one()

    active_teachers = session.exec(
        select(func.count()).select_from(Teacher).where(Teacher.is_active.is_(True))
    ).one()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "admin": admin,
            "active_school_students": active_school_students,
            "active_academy_students": active_academy_students,
            "active_teachers": active_teachers,
        },
    )
