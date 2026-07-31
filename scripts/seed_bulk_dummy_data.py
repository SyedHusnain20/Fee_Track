"""Bulk dummy-data seed script -- WIPES existing student-linked data, then
seeds a large, fully random batch for demoing/load-testing at scale.
Interactive confirmation required before it does anything.

This supersedes seed_dummy_data.py's small fixed-batch approach with:
  - A wipe step: deletes all Student, Enrollment, FeeCycle, and
    AttendanceRecord rows first (child tables before Student, to satisfy
    FK constraints). AdminUser, ClassLevel, CategoryFeeDefault, and
    SystemSetting rows are left untouched -- this clears student-linked
    data only, so you don't get locked out and don't have to re-run
    seed_reference_data.py.
  - TOTAL_STUDENTS students (>= 500), each assigned a RANDOM class level
    (not a fixed per-level batch), so the distribution across classes is
    organic rather than an even split.
  - Each student is School-track or Academy-track, same mutual
    exclusivity seed_dummy_data.py uses (mirrors real behavior) -- School
    is only offered where eligible (Class 10 and below, i.e.
    class_offset <= SCHOOL_MAX_ELIGIBLE_OFFSET), and roughly half of
    eligible students land there; everyone else gets 1-2 Academy
    categories (Coaching/English/Computer).
  - A random discount per enrollment. ASSUMPTION: this picks any non-NONE
    DiscountType member and guesses a value from its name (see
    _random_discount below). If your DiscountType members aren't named
    along PERCENT*/flat-amount lines, adjust that one function.
  - FEE_CYCLE_MONTHS (12) months of fee cycles via the REAL
    generate_fee_cycles() service, called once per period -- same
    banding logic as the "Generate" button, just looped across a year.
    Older months are marked Paid more often than the current one, for a
    realistic collections trend instead of a flat 50/50 split.
  - ATTENDANCE_DAYS (30) days of attendance, same on-time/late/absent
    logic (School, checked against the real configured start
    time/grace) and present/absent logic (Academy) as seed_dummy_data.py.

Does NOT touch teachers -- there's no Teacher-related model in the
codebase this script was written against, so teacher seeding isn't
included here. See chat for a follow-up on that.

Usage:
    docker compose exec api python scripts/seed_bulk_dummy_data.py
"""

import random
import sys
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete as sa_delete
from sqlalchemy import func
from sqlmodel import Session, select

from app.core.database import engine
from app.core.timezone import school_today
from app.models.admin_user import AdminUser
from app.models.attendance_record import AttendanceRecord
from app.models.class_level import ClassLevel
from app.models.enrollment import Enrollment
from app.models.enums import (
    AttendanceSession,
    DiscountType,
    EnrollmentStatus,
    FeeCategory,
    FeeCycleStatus,
    PunctualityStatus,
)
from app.models.fee_cycle import FeeCycle
from app.models.student import Student
from app.services.attendance_settings import get_session_grace_minutes, get_session_start_time
from app.services.fee_cycle_generation import generate_fee_cycles
from app.services.qr_token import generate_qr_token
from app.services.roll_number import generate_roll_number

TOTAL_STUDENTS = 520  # >= 500, spread randomly across every class level
SCHOOL_MAX_ELIGIBLE_OFFSET = 12  # Class 10 -- matches the real fee-band ceiling
FEE_CYCLE_MONTHS = 12  # trailing 12 months of fee cycles
ATTENDANCE_DAYS = 30  # trailing 30 days of attendance
ACADEMY_CATEGORIES = [FeeCategory.COACHING, FeeCategory.ENGLISH, FeeCategory.COMPUTER]

FIRST_NAMES = [
    "Ali", "Hamza", "Bilal", "Zain", "Ahmed", "Usman", "Hassan", "Hussain",
    "Fahad", "Owais", "Saad", "Talha", "Faizan", "Danish", "Rayyan", "Omer",
    "Shahzaib", "Waleed", "Arham", "Ibrahim", "Fatima", "Ayesha", "Zainab",
    "Maryam", "Sana", "Amna", "Hira", "Sadia", "Rabia", "Iqra",
]
LAST_NAMES = [
    "Khan", "Sheikh", "Raza", "Malik", "Siddiqui", "Ansari", "Qureshi",
    "Baig", "Abbasi", "Chaudhry", "Farooq", "Iqbal", "Memon", "Shah", "Soomro",
]


def _random_name() -> str:
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"


def _random_father_name() -> str:
    return f"Muhammad {random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"


def _random_whatsapp() -> str:
    return f"+92 3{random.randint(0, 4)}{random.randint(0, 9)} {random.randint(1000000, 9999999)}"


def _random_discount() -> tuple[DiscountType, Decimal | None]:
    """~55% of enrollments get no discount. For the rest, picks any
    non-NONE DiscountType member and guesses a value from its name:
    PERCENT* -> 5-50%, anything else -> a flat rupee amount. Adjust the
    branch below if your real DiscountType members are named differently.
    """
    if random.random() < 0.55:
        return DiscountType.NONE, None

    choices = [d for d in DiscountType if d != DiscountType.NONE]
    if not choices:
        return DiscountType.NONE, None
    discount_type = random.choice(choices)

    if "PERCENT" in discount_type.name.upper():
        value = Decimal(random.choice([5, 10, 15, 20, 25, 30, 50]))
    else:
        value = Decimal(random.choice([100, 200, 300, 500, 750, 1000]))
    return discount_type, value


def wipe_existing_data(session: Session) -> None:
    """Deletes Student and everything that hangs off it (Enrollment,
    FeeCycle, AttendanceRecord), child tables first for FK safety.
    AdminUser, ClassLevel, CategoryFeeDefault, and SystemSetting are left
    untouched.
    """
    models = [
        ("AttendanceRecord", AttendanceRecord),
        ("FeeCycle", FeeCycle),
        ("Enrollment", Enrollment),
        ("Student", Student),
    ]
    print("Existing rows to be wiped:")
    for label, model in models:
        count = session.exec(select(func.count()).select_from(model)).one()
        print(f"  {label}: {count}")

    for _, model in models:
        session.execute(sa_delete(model))
    session.commit()
    print("Existing student-linked data wiped.\n")


def _create_student(session: Session, class_level: ClassLevel, enrollment_year: int) -> Student:
    roll_number = generate_roll_number(
        session, class_level_id=class_level.id, enrollment_year=enrollment_year
    )
    student = Student(
        roll_number=roll_number,
        name=_random_name(),
        father_name=_random_father_name(),
        parent_whatsapp=_random_whatsapp(),
        qr_code=generate_qr_token(),
        class_level_id=class_level.id,
        is_active=True,
    )
    session.add(student)
    session.flush()
    return student


def _enroll(
    session: Session,
    student: Student,
    category: FeeCategory,
    admin_id: int,
    discount_type: DiscountType,
    discount_value: Decimal | None,
) -> None:
    session.add(
        Enrollment(
            student_id=student.id,
            category=category,
            discount_type=discount_type,
            discount_value=discount_value,
            status=EnrollmentStatus.ACTIVE,
            created_by_id=admin_id,
        )
    )


def seed_students(
    session: Session, admin_id: int, total_students: int
) -> tuple[list[Student], list[Student]]:
    class_levels = session.exec(select(ClassLevel).order_by(ClassLevel.class_offset)).all()
    if not class_levels:
        raise RuntimeError("No ClassLevel rows found -- run scripts/seed_reference_data.py first.")

    current_year = school_today().year
    school_group: list[Student] = []
    academy_group: list[Student] = []

    for _ in range(total_students):
        class_level = random.choice(class_levels)
        school_eligible = class_level.class_offset <= SCHOOL_MAX_ELIGIBLE_OFFSET

        student = _create_student(session, class_level, current_year)

        if school_eligible and random.random() < 0.5:
            discount_type, discount_value = _random_discount()
            _enroll(session, student, FeeCategory.SCHOOL, admin_id, discount_type, discount_value)
            school_group.append(student)
        else:
            chosen = random.sample(ACADEMY_CATEGORIES, k=random.choice([1, 1, 2]))
            for category in chosen:
                discount_type, discount_value = _random_discount()
                _enroll(session, student, category, admin_id, discount_type, discount_value)
            academy_group.append(student)

    session.commit()
    return school_group, academy_group


def _period_string(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def _last_n_periods(reference_date: date, n: int) -> list[str]:
    """Oldest-first list of the n periods ending at reference_date's month."""
    periods = []
    year, month = reference_date.year, reference_date.month
    for _ in range(n):
        periods.append(_period_string(year, month))
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    return list(reversed(periods))


def _random_date_in_period(period: str) -> date:
    year, month = (int(part) for part in period.split("-"))
    return date(year, month, random.randint(1, 28))


def seed_fee_cycles(session: Session, admin_id: int, dummy_students: list[Student]) -> None:
    today = school_today()
    periods = _last_n_periods(today, FEE_CYCLE_MONTHS)
    dummy_ids = {s.id for s in dummy_students}

    for index, period in enumerate(periods):
        # Reuses the REAL generation service -- same one the "Generate"
        # button calls -- so amounts are correctly banded across all 12
        # months. This will also generate cycles for any pre-existing real
        # students without one yet for that period -- expected behavior of
        # the real service, not something this script should suppress.
        result = generate_fee_cycles(session, period=period, admin_id=admin_id)
        session.commit()
        print(f"Fee cycles generated for {period}: {result}")

        cycles = session.exec(
            select(FeeCycle).where(FeeCycle.period == period, FeeCycle.student_id.in_(dummy_ids))
        ).all()

        # Older months collect more reliably than the current one -- gives
        # a realistic collections trend instead of a flat 50/50 split.
        months_ago = FEE_CYCLE_MONTHS - 1 - index
        paid_probability = 0.4 if months_ago == 0 else min(0.5 + months_ago * 0.05, 0.92)

        paid_count = 0
        for cycle in cycles:
            if random.random() < paid_probability:
                cycle.status = FeeCycleStatus.PAID
                cycle.paid_date = (
                    today - timedelta(days=random.randint(0, 25))
                    if months_ago == 0
                    else _random_date_in_period(period)
                )
                cycle.updated_by_id = admin_id
                session.add(cycle)
                paid_count += 1
        session.commit()
        print(f"  Marked {paid_count} of {len(cycles)} dummy fee cycles Paid for {period}.")


def _compute_punctuality(arrival: time, start_time: time, grace_minutes: int) -> PunctualityStatus:
    anchor = date(2000, 1, 1)
    cutoff = (datetime.combine(anchor, start_time) + timedelta(minutes=grace_minutes)).time()
    return PunctualityStatus.ON_TIME if arrival <= cutoff else PunctualityStatus.LATE


def seed_attendance(
    session: Session,
    school_group_students: list[Student],
    academy_group_students: list[Student],
) -> None:
    today = school_today()
    last_n_days = [today - timedelta(days=offset) for offset in range(ATTENDANCE_DAYS - 1, -1, -1)]

    school_start = get_session_start_time(session, AttendanceSession.SCHOOL)
    school_grace = get_session_grace_minutes(session, AttendanceSession.SCHOOL)
    academy_start = get_session_start_time(session, AttendanceSession.ACADEMY)

    anchor = date(2000, 1, 1)
    records_created = 0

    for student in school_group_students:
        for day in last_n_days:
            outcome = random.choices(["on_time", "late", "absent"], weights=[60, 20, 20], k=1)[0]
            if outcome == "absent" or school_start is None:
                continue
            if outcome == "on_time":
                minutes_offset = random.randint(-30, school_grace)
            else:
                minutes_offset = random.randint(school_grace + 1, school_grace + 45)
            arrival_dt = datetime.combine(anchor, school_start) + timedelta(minutes=minutes_offset)
            arrival_time = max(arrival_dt.time(), time(0, 1))
            punctuality = _compute_punctuality(arrival_time, school_start, school_grace)
            session.add(
                AttendanceRecord(
                    student_id=student.id,
                    scan_date=day,
                    arrival_time=arrival_time,
                    session=AttendanceSession.SCHOOL,
                    punctuality_status=punctuality,
                )
            )
            records_created += 1

    for student in academy_group_students:
        for day in last_n_days:
            present = random.random() < 0.75
            if not present:
                continue
            base = academy_start or time(16, 0)
            arrival_dt = datetime.combine(anchor, base) + timedelta(minutes=random.randint(-15, 90))
            arrival_time = max(arrival_dt.time(), time(0, 1))
            session.add(
                AttendanceRecord(
                    student_id=student.id,
                    scan_date=day,
                    arrival_time=arrival_time,
                    session=AttendanceSession.ACADEMY,
                    punctuality_status=None,
                )
            )
            records_created += 1

    session.commit()
    print(f"Attendance records created: {records_created} (across last {ATTENDANCE_DAYS} days).")


def main() -> None:
    with Session(engine) as session:
        admin = session.exec(select(AdminUser)).first()
        if admin is None:
            print(
                "No AdminUser found -- create a super admin first (scripts/create_super_admin.py)."
            )
            return

        print(
            f"This will WIPE all existing Student, Enrollment, FeeCycle, and "
            f"AttendanceRecord rows, then create {TOTAL_STUDENTS} dummy students spread "
            f"randomly across every class level and fee category, each with a random "
            f"discount, {FEE_CYCLE_MONTHS} months of fee cycles, and {ATTENDANCE_DAYS} "
            f"days of attendance."
        )
        print("Admin accounts, ClassLevel, CategoryFeeDefault, and SystemSetting rows are kept.")
        confirm = input("Type 'yes' to continue: ").strip().lower()
        if confirm != "yes":
            print("Aborted -- nothing was changed.")
            return

        wipe_existing_data(session)

        school_group, academy_group = seed_students(session, admin.id, TOTAL_STUDENTS)
        print(
            "Students created: "
            f"{len(school_group)} School-track, "
            f"{len(academy_group)} Academy-track "
            f"({len(school_group) + len(academy_group)} total)."
        )

        all_students = school_group + academy_group
        seed_fee_cycles(session, admin.id, all_students)
        seed_attendance(session, school_group, academy_group)

    print("Done.")


if __name__ == "__main__":
    main()