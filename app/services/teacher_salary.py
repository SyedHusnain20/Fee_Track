"""Teacher monthly attendance-based salary — Phase 3, revised in Phase 4
for split School/Academy salary calculation.

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
dock a teacher's pay any more than it marks a student absent.

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

Phase 4 (dual-enrollment split salary): a teacher enrolled in BOTH
School and Academy scans attendance separately for each (two
AttendanceSession values, two independent daily scans — see
app.services.attendance). Their salary is treated as half-for-School,
half-for-Academy, and each half gets its own present/absent count from
that session's scans only, then the two net-salary halves are summed:

    school_share  = salary / 2
    academy_share = salary / 2
    net_salary = (school_share - school_share/30 * school_absent_days)
               + (academy_share - academy_share/30 * academy_absent_days)

A teacher enrolled in only ONE of School/Academy is unaffected by this
split — they get 100% of their salary, docked against absences from just
that one session, same formula as before Phase 4 (this just makes the
formula session-scoped instead of "present in either session," which
matters now that a dual-enrolled teacher can legitimately be absent from
one session on a day they attended the other).

Teachers with NEITHER teaches_school nor teaches_coaching set (legacy
rows from before the School/Academy-only enrollment rule — see
app/api/teachers.py) fall back to the pre-Phase-4 behavior: full salary,
"present" if they scanned either session that day. This only applies to
old data; the form has required at least one of School/Academy since
Phase 4.
"""

import calendar
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlmodel import Session, select

from app.core.timezone import school_today
from app.models.attendance_record import AttendanceRecord
from app.models.enums import AttendanceSession
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


def _session_attendance_breakdown(
    session: Session,
    teacher: Teacher,
    working_days: list[date],
    salary_share: Optional[Decimal],
    attendance_session: Optional[AttendanceSession] = None,
) -> dict:
    """Present/absent/net-salary for one salary "share" over the given
    working days. attendance_session=None means "present in either
    session" — used only for the legacy neither-flag-set fallback;
    otherwise scoped to exactly that session's scans."""
    present_days = 0
    if working_days:
        query = select(AttendanceRecord.scan_date).where(
            AttendanceRecord.teacher_id == teacher.id,
            AttendanceRecord.scan_date >= working_days[0],
            AttendanceRecord.scan_date <= working_days[-1],
        )
        if attendance_session is not None:
            query = query.where(AttendanceRecord.session == attendance_session)
        present_dates = set(session.exec(query).all())
        present_days = sum(1 for d in working_days if d in present_dates)

    absent_days = len(working_days) - present_days

    # No net_salary if there were no working days to count at all -- most
    # commonly because the teacher hadn't joined yet during this period.
    # "salary minus zero absences" would otherwise silently show a full
    # month's pay for someone who wasn't employed for any of it.
    net_salary: Optional[Decimal] = None
    if salary_share is not None and working_days:
        daily_rate = salary_share / SALARY_DIVISOR
        net_salary = (salary_share - daily_rate * absent_days).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    return {
        "working_days": len(working_days),
        "present_days": present_days,
        "absent_days": absent_days,
        "net_salary": net_salary,
    }


def compute_teacher_monthly_salary(
    session: Session,
    teacher: Teacher,
    year: Optional[int] = None,
    month: Optional[int] = None,
) -> dict:
    """Attendance + salary breakdown for one calendar month (defaults to
    the current one). net_salary is None when the teacher has no salary
    set (nullable for the handful of pre-Phase-1 rows) — there's nothing
    to deduct a per-day rate from.

    Returns a dict with a top-level combined net_salary, plus a "school"
    and/or "academy" breakdown (each with its own working/present/absent
    days and net_salary share) for whichever categories the teacher is
    enrolled in. A legacy teacher enrolled in neither gets a single
    "combined" breakdown instead, using the old either-session behavior."""
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

    enrolled_school = teacher.teaches_school
    enrolled_academy = teacher.teaches_coaching
    both = enrolled_school and enrolled_academy

    result = {
        "year": year,
        "month": month,
        "period_label": date(year, month, 1).strftime("%B %Y"),
        "is_month_complete": not (year == today.year and month == today.month),
        "school": None,
        "academy": None,
        "net_salary": None,
    }

    if not enrolled_school and not enrolled_academy:
        # Legacy fallback: no School/Academy flag set (predates the
        # Phase-4 "at least one" rule). Old behavior — full salary,
        # present if scanned either session.
        result["combined"] = _session_attendance_breakdown(
            session, teacher, working_days, teacher.salary, attendance_session=None
        )
        result["net_salary"] = result["combined"]["net_salary"]
        return result

    salary_share = (
        teacher.salary / 2 if (both and teacher.salary is not None) else teacher.salary
    )

    if enrolled_school:
        result["school"] = _session_attendance_breakdown(
            session, teacher, working_days, salary_share, AttendanceSession.SCHOOL
        )
    if enrolled_academy:
        result["academy"] = _session_attendance_breakdown(
            session, teacher, working_days, salary_share, AttendanceSession.ACADEMY
        )

    # Combined net salary = sum of whichever share(s) apply. If there
    # were no working days at all, there's nothing to report (matches
    # the pre-Phase-4 "no working days -> no net_salary" behavior).
    parts = [p for p in (result["school"], result["academy"]) if p is not None]
    net_salary_parts = [p["net_salary"] for p in parts if p["net_salary"] is not None]
    if working_days and net_salary_parts:
        result["net_salary"] = sum(net_salary_parts).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    return result
