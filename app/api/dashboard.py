"""Admin dashboard landing page.

This is what Step 6's login POST redirects to. School vs Academy student
counts use the same student-has-an-active-enrollment-in-this-category-set
pattern as /students' filters (app/api/students.py) — verified there to
correctly count a student enrolled in both groups toward both counts,
without double-counting rows, since these are COUNT queries against
Student with an IN-subquery filter, not a join.

Phase 4 [dashboard rework]: three more panels beyond the original stat
cards — today's attendance snapshot, the last 10 kiosk scans, and this
month's fee collection snapshot. The fee panel reuses
app.services.fee_settings' due-day setting from Phase 3, so "overdue"
means exactly the same thing here as it does on /students.
"""

from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlmodel import Session, select

from app.api.deps import get_current_admin
from app.core.database import get_session
from app.core.timezone import school_today
from app.models.admin_user import AdminUser
from app.models.attendance_record import AttendanceRecord
from app.models.enrollment import Enrollment
from app.models.enums import (
    AttendanceSession,
    EnrollmentStatus,
    FeeCategory,
    FeeCycleStatus,
    PunctualityStatus,
)
from app.models.fee_cycle import FeeCycle
from app.models.student import Student
from app.models.teacher import Teacher
from app.services.fee_settings import get_fee_due_day

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")

SESSION_LABELS = {AttendanceSession.SCHOOL: "School", AttendanceSession.ACADEMY: "Academy"}
PUNCTUALITY_LABELS = {PunctualityStatus.ON_TIME: "On time", PunctualityStatus.LATE: "Late"}


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

    today = school_today()

    # --- Today's attendance snapshot ------------------------------------
    school_scanned_today = session.exec(
        select(func.count())
        .select_from(AttendanceRecord)
        .where(
            AttendanceRecord.scan_date == today,
            AttendanceRecord.session == AttendanceSession.SCHOOL,
            AttendanceRecord.student_id.is_not(None),
        )
    ).one()
    academy_scanned_today = session.exec(
        select(func.count())
        .select_from(AttendanceRecord)
        .where(
            AttendanceRecord.scan_date == today,
            AttendanceRecord.session == AttendanceSession.ACADEMY,
            AttendanceRecord.student_id.is_not(None),
        )
    ).one()
    # distinct() because a teacher can have one row per session per day
    # (School and Academy both), and this stat means "how many distinct
    # teachers checked in today", not "how many teacher scans happened".
    teachers_scanned_today = session.exec(
        select(func.count(func.distinct(AttendanceRecord.teacher_id)))
        .select_from(AttendanceRecord)
        .where(
            AttendanceRecord.scan_date == today,
            AttendanceRecord.teacher_id.is_not(None),
        )
    ).one()

    # --- Last 10 kiosk scans, most recent first --------------------------
    recent_records = session.exec(
        select(AttendanceRecord)
        .order_by(
            AttendanceRecord.scan_date.desc(),
            AttendanceRecord.arrival_time.desc(),
            AttendanceRecord.id.desc(),
        )
        .limit(10)
    ).all()

    recent_scans = []
    for record in recent_records:
        if record.student_id is not None:
            person_type = "Student"
            name = record.student.name
            identifier = record.student.roll_number
        else:
            person_type = "Teacher"
            name = record.teacher.name
            identifier = record.teacher.staff_id
        recent_scans.append(
            {
                "person_type": person_type,
                "name": name,
                "identifier": identifier,
                "session_label": SESSION_LABELS[record.session],
                "scan_date": record.scan_date,
                "arrival_time": record.arrival_time,
                "punctuality_label": PUNCTUALITY_LABELS.get(record.punctuality_status),
            }
        )

    # --- This month's fee snapshot ----------------------------------------
    # overdue_count counts unpaid FeeCycle rows for the current period
    # rather than re-deriving each active student's total fee from scratch
    # (as /students does per row) — FeeCycle.total_due is the snapshotted
    # amount owed, and generate_fee_cycles() never creates a row for a
    # zero-due student, so "an unpaid cycle exists" already means "this
    # student owes money and hasn't paid," matching /students' definition.
    current_period = f"{today.year:04d}-{today.month:02d}"
    due_day = get_fee_due_day(session)
    is_past_due_day = today.day > due_day

    cycles_this_period = session.exec(
        select(FeeCycle).where(FeeCycle.period == current_period)
    ).all()
    cycles_generated_count = len(cycles_this_period)
    fee_collected = sum(
        (c.total_due for c in cycles_this_period if c.status == FeeCycleStatus.PAID),
        Decimal("0.00"),
    )
    fee_outstanding = sum(
        (c.total_due for c in cycles_this_period if c.status == FeeCycleStatus.UNPAID),
        Decimal("0.00"),
    )
    unpaid_count = sum(1 for c in cycles_this_period if c.status == FeeCycleStatus.UNPAID)
    overdue_count = unpaid_count if is_past_due_day else 0

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "admin": admin,
            "today": today,
            "active_school_students": active_school_students,
            "active_academy_students": active_academy_students,
            "active_teachers": active_teachers,
            "school_scanned_today": school_scanned_today,
            "academy_scanned_today": academy_scanned_today,
            "teachers_scanned_today": teachers_scanned_today,
            "recent_scans": recent_scans,
            "current_period": current_period,
            "cycles_generated_count": cycles_generated_count,
            "fee_collected": fee_collected,
            "fee_outstanding": fee_outstanding,
            "unpaid_count": unpaid_count,
            "overdue_count": overdue_count,
            "is_past_due_day": is_past_due_day,
            "due_day": due_day,
        },
    )
