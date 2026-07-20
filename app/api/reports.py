"""Admin attendance reporting — Step 10. GET /reports/attendance: date
range + session (School/Academy) + name/ID search, students and teachers
shown in separate sections. Read-only — no export yet, per current scope;
export buttons can be added later without touching this query logic.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, or_, select

from app.api.deps import get_current_admin
from app.core.database import get_session
from app.models.admin_user import AdminUser
from app.models.attendance_record import AttendanceRecord
from app.models.enums import AttendanceSession
from app.models.student import Student
from app.models.teacher import Teacher

router = APIRouter(prefix="/reports", tags=["reports"])
templates = Jinja2Templates(directory="app/templates")

SESSION_LABELS = {
    AttendanceSession.SCHOOL: "School",
    AttendanceSession.ACADEMY: "Academy",
}


@router.get("/attendance", response_class=HTMLResponse)
async def attendance_report(
    request: Request,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    search: Optional[str] = None,
    attendance_session: Optional[AttendanceSession] = Query(None, alias="session"),
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    # No range given yet (first load) -> default to today only, rather than
    # dumping the whole table's history unfiltered.
    today = date.today()
    effective_start = start_date or today
    effective_end = end_date or today
    if effective_start > effective_end:
        effective_start, effective_end = effective_end, effective_start

    search_term = search.strip() if search else ""

    student_query = (
        select(AttendanceRecord, Student)
        .join(Student, AttendanceRecord.student_id == Student.id)
        .where(
            AttendanceRecord.scan_date >= effective_start,
            AttendanceRecord.scan_date <= effective_end,
        )
        .order_by(AttendanceRecord.scan_date.desc(), AttendanceRecord.arrival_time.desc())
    )
    if attendance_session:
        student_query = student_query.where(AttendanceRecord.session == attendance_session)
    if search_term:
        like = f"%{search_term}%"
        student_query = student_query.where(
            or_(Student.name.ilike(like), Student.roll_number.ilike(like))
        )

    teacher_query = (
        select(AttendanceRecord, Teacher)
        .join(Teacher, AttendanceRecord.teacher_id == Teacher.id)
        .where(
            AttendanceRecord.scan_date >= effective_start,
            AttendanceRecord.scan_date <= effective_end,
        )
        .order_by(AttendanceRecord.scan_date.desc(), AttendanceRecord.arrival_time.desc())
    )
    if attendance_session:
        teacher_query = teacher_query.where(AttendanceRecord.session == attendance_session)
    if search_term:
        like = f"%{search_term}%"
        teacher_query = teacher_query.where(
            or_(Teacher.name.ilike(like), Teacher.staff_id.ilike(like))
        )

    student_rows = session.exec(student_query).all()
    teacher_rows = session.exec(teacher_query).all()

    return templates.TemplateResponse(
        "reports/attendance.html",
        {
            "request": request,
            "admin": admin,
            "student_rows": student_rows,
            "teacher_rows": teacher_rows,
            "start_date": effective_start,
            "end_date": effective_end,
            "attendance_session": attendance_session,
            "search": search_term,
            "sessions": list(AttendanceSession),
            "session_labels": SESSION_LABELS,
        },
    )