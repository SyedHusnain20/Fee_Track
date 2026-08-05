"""Teacher monthly attendance-based salary — Phase 3.

    net_salary = salary - (salary / 30) * absent_days

Attendance capture: teachers scan the SAME QR kiosk as students (see
app.services.attendance.process_scan, which already resolves a scanned
token to either a Student or a Teacher). No new capture flow or table was
needed here — a teacher's scans already land in AttendanceRecord kept
structurally separate from student scans via the mutually-exclusive
student_id/teacher_id columns (ck_attendance_exactly_one_owner) and two
separate partial unique indexes, one per owner type. This module only
reads that existing data, scoped to teacher_id.

"Working days" reuses this codebase's existing "academic day" convention
from app/api/reports.py's attendance report: every calendar day except
Sunday (Saturday counts as a working day) and every date marked in the
Holiday table (see app.services.holidays) -- a school closure doesn't
dock a teacher's pay any more than it marks a student absent. A teacher
counts as present on a working day if they have at least one
AttendanceRecord that day, in either session (School or Academy) — which
one doesn't matter for payroll purposes.

For the current, still-in-progress month, only working days up to and
including today are counted, so the figure shown updates live through the
month rather than treating not-yet-arrived future days as absences. A
fully elapsed past month counts every working day in it -- except days
before the teacher's date_joined, which are excluded rather than counted
as absences (a teacher hired on the 30th isn't "absent" for the 29 days
before that). Teachers with no date_joined on record (pre-existing rows
from before that field was added) fall back to counting from the 1st.

The salary/30 divisor is fixed regardless of how many days are actually
in the given month (28-31) — a flat 30-day baseline, matching how the
formula was specified rather than a per-month daily-rate recalculation.
"""

import calendar
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlmodel import Session, select

from app.core.timezone import school_today
from app.models.attendance_record import AttendanceRecord
from app.models.teacher import Teacher
from app.services.holidays import get_holiday_dates_in_range

SALARY_DIVISOR = Decimal(30)


def _working_days_in_period(
    year: int,
    month: int,
    today: date,
    hire_date: Optional[date] = None,
    holiday_dates: frozenset = frozenset(),
) -> list[date]:
    """Every non-Sunday, non-holiday calendar day in the given month,
    capped at `today` when the month is the one currently in progress,
    and starting no earlier than `hire_date` when that falls inside (or
    after) this month -- a teacher can't be "absent" on a day before they
    joined. Returns an empty list if the teacher hadn't joined by the end
    of the window at all (e.g. hired later in the month than `today`)."""
    last_day = calendar.monthrange(year, month)[1]
    month_start = date(year, month, 1)
    month_end = date(year, month, last_day)

    end_date = today if (year == today.year and month == today.month) else month_end
    start_date = month_start
    if hire_date is not None and hire_date > start_date:
        start_date = hire_date

    if start_date > end_date:
        return []

    days = []
    d = start_date
    while d <= end_date:
        if d.weekday() != 6 and d not in holiday_dates:  # Monday=0 ... Sunday=6
            days.append(d)
        d += timedelta(days=1)
    return days


def compute_teacher_monthly_salary(
    session: Session,
    teacher: Teacher,
    year: Optional[int] = None,
    month: Optional[int] = None,
) -> dict:
    """Attendance + salary breakdown for one calendar month (defaults to
    the current one). net_salary is None when the teacher has no salary
    set (nullable for the handful of pre-Phase-1 rows) — there's nothing
    to deduct a per-day rate from."""
    today = school_today()
    year = year or today.year
    month = month or today.month

    last_day = calendar.monthrange(year, month)[1]
    holiday_dates = get_holiday_dates_in_range(
        session, date(year, month, 1), date(year, month, last_day)
    )
    working_days = _working_days_in_period(
        year, month, today, hire_date=teacher.date_joined, holiday_dates=holiday_dates
    )

    present_days = 0
    if working_days:
        present_dates = set(
            session.exec(
                select(AttendanceRecord.scan_date).where(
                    AttendanceRecord.teacher_id == teacher.id,
                    AttendanceRecord.scan_date >= working_days[0],
                    AttendanceRecord.scan_date <= working_days[-1],
                )
            ).all()
        )
        present_days = sum(1 for d in working_days if d in present_dates)

    absent_days = len(working_days) - present_days

    # No net_salary if there were no working days to count at all -- most
    # commonly because the teacher hadn't joined yet during this period.
    # "salary minus zero absences" would otherwise silently show a full
    # month's pay for someone who wasn't employed for any of it.
    net_salary: Optional[Decimal] = None
    if teacher.salary is not None and working_days:
        daily_rate = teacher.salary / SALARY_DIVISOR
        net_salary = (teacher.salary - daily_rate * absent_days).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    return {
        "year": year,
        "month": month,
        "period_label": date(year, month, 1).strftime("%B %Y"),
        "is_month_complete": not (year == today.year and month == today.month),
        "working_days": len(working_days),
        "present_days": present_days,
        "absent_days": absent_days,
        "net_salary": net_salary,
    }
