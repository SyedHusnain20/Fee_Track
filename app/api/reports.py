"""Admin reporting — two per-student modules, both reached by searching a
student by roll number or name (no picker step; every match renders its
own report card stacked on the page):

- Fee Reports (/reports/fees): a searched student's last 12 calendar
  months of FeeCycle history — paid/unpaid + payment date per month.
  Months with no FeeCycle row (not yet generated, or the student owed
  nothing that month — fee_cycle_generation.py skips zero-due students
  entirely) show as "No cycle" rather than being silently omitted.

- Attendance Reports (/reports/attendance): a searched student's last 30
  "academic days" — calendar days going back from today, skipping Sundays
  only (Saturdays count; there's no broader holiday calendar in this
  system). Scoped to the School session specifically, since Present/
  Late/Absent is School's punctuality model — Academy scans have no late
  judgment at all (see AttendanceRecord.punctuality_status). Percentage
  counts Late as Present, per explicit spec.

Replaces the old date-range + session + school/teacher listing that used
to live at this URL (Step 10) — that view mixed all students and teachers
in one flat list for an arbitrary date range, which doesn't answer "how
is this one student doing," the question these two reports are for.
"""

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, or_, select

from app.api.deps import get_current_admin
from app.core.database import get_session
from app.core.timezone import school_today
from app.models.admin_user import AdminUser
from app.models.attendance_record import AttendanceRecord
from app.models.enums import AttendanceSession, FeeCycleStatus, PunctualityStatus
from app.models.fee_cycle import FeeCycle
from app.models.student import Student

router = APIRouter(prefix="/reports", tags=["reports"])
templates = Jinja2Templates(directory="app/templates")

# Cap on how many matching students get a full report rendered per search,
# so a broad search term (e.g. a common father's-name substring) can't
# accidentally render dozens of 12- or 30-row tables on one page.
MAX_MATCHES = 10


def _find_students(session: Session, search_term: str) -> tuple[list[Student], bool]:
    """Returns (matches, was_truncated)."""
    like = f"%{search_term}%"
    rows = session.exec(
        select(Student)
        .where(or_(Student.name.ilike(like), Student.roll_number.ilike(like)))
        .order_by(Student.roll_number)
        .limit(MAX_MATCHES + 1)
    ).all()
    truncated = len(rows) > MAX_MATCHES
    return rows[:MAX_MATCHES], truncated


def _last_n_periods(today: date, n: int) -> list[str]:
    """Last n "YYYY-MM" period strings, most recent (current month) first."""
    periods = []
    year, month = today.year, today.month
    for _ in range(n):
        periods.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    return periods


def _period_label(period: str) -> str:
    year, month = period.split("-")
    return date(int(year), int(month), 1).strftime("%B %Y")


def _last_n_academic_days(today: date, n: int) -> list[date]:
    """Last n calendar days up to and including today, skipping Sundays."""
    days: list[date] = []
    d = today
    while len(days) < n:
        if d.weekday() != 6:  # Monday=0 ... Sunday=6
            days.append(d)
        d -= timedelta(days=1)
    return days


@router.get("", response_class=HTMLResponse)
async def reports_index(
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
):
    return templates.TemplateResponse(
        "reports/index.html",
        {"request": request, "admin": admin},
    )


@router.get("/fees", response_class=HTMLResponse)
async def fee_report(
    request: Request,
    search: Optional[str] = None,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    search_term = search.strip() if search else ""
    today = school_today()
    periods = _last_n_periods(today, 12)

    students: list[Student] = []
    truncated = False
    reports = []

    if search_term:
        students, truncated = _find_students(session, search_term)
        for student in students:
            cycles = session.exec(
                select(FeeCycle).where(
                    FeeCycle.student_id == student.id,
                    FeeCycle.period.in_(periods),
                )
            ).all()
            cycle_by_period = {c.period: c for c in cycles}

            month_rows = []
            for period in periods:
                cycle = cycle_by_period.get(period)
                if cycle is None:
                    month_rows.append({
                        "period_label": _period_label(period),
                        "status": "No cycle",
                        "paid_date": None,
                    })
                else:
                    month_rows.append({
                        "period_label": _period_label(period),
                        "status": "Paid" if cycle.status == FeeCycleStatus.PAID else "Unpaid",
                        "paid_date": cycle.paid_date,
                        "total_due": cycle.total_due,
                    })

            reports.append({"student": student, "month_rows": month_rows})

    return templates.TemplateResponse(
        "reports/fees.html",
        {
            "request": request,
            "admin": admin,
            "search": search_term,
            "reports": reports,
            "truncated": truncated,
        },
    )


@router.get("/attendance", response_class=HTMLResponse)
async def attendance_report(
    request: Request,
    search: Optional[str] = None,
    session: Session = Depends(get_session),
    admin: AdminUser = Depends(get_current_admin),
):
    search_term = search.strip() if search else ""
    today = school_today()
    academic_days = _last_n_academic_days(today, 30)
    day_set = set(academic_days)

    students: list[Student] = []
    truncated = False
    reports = []

    if search_term:
        students, truncated = _find_students(session, search_term)
        for student in students:
            records = session.exec(
                select(AttendanceRecord).where(
                    AttendanceRecord.student_id == student.id,
                    AttendanceRecord.session == AttendanceSession.SCHOOL,
                    AttendanceRecord.scan_date.in_(day_set),
                )
            ).all()
            record_by_day = {r.scan_date: r for r in records}

            day_rows = []
            present_count = 0
            late_count = 0
            absent_count = 0
            for day in academic_days:
                record = record_by_day.get(day)
                if record is None:
                    status_label = "Absent"
                    absent_count += 1
                elif record.punctuality_status == PunctualityStatus.LATE:
                    status_label = "Late"
                    late_count += 1
                else:
                    status_label = "Present"
                    present_count += 1
                day_rows.append({
                    "day": day,
                    "weekday": day.strftime("%a"),
                    "status": status_label,
                })

            total = len(academic_days)
            percentage = round((present_count + late_count) / total * 100, 1) if total else 0.0

            reports.append({
                "student": student,
                "day_rows": day_rows,
                "present_count": present_count,
                "late_count": late_count,
                "absent_count": absent_count,
                "percentage": percentage,
            })

    return templates.TemplateResponse(
        "reports/attendance.html",
        {
            "request": request,
            "admin": admin,
            "search": search_term,
            "reports": reports,
            "truncated": truncated,
            "window_size": len(academic_days),
        },
    )
