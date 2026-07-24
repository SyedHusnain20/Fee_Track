"""One-off dummy-data seed script — NOT idempotent, re-running adds another
full batch rather than skipping duplicates. Interactive confirmation
required before it does anything.

Generates, per ClassLevel:
  - 10 "School group" students (School enrollment only) — SKIPPED for
    Class 11/12, since School enrollment is blocked above Class 10 by the
    real fee-band ceiling (get_band_fee) — this script doesn't bypass that
    validation, it goes through the same rule the live app enforces.
  - 10 "Academy group" students (1-2 of Coaching/English/Computer) — for
    every class level, since Academy's bands cover the full range.

That's 13 school-eligible levels x 10 + 15 levels x 10 = 280 students.

Then, for the current period:
  - Calls the REAL generate_fee_cycles() service (same one the "Generate"
    button uses) so amounts are correctly banded, not hand-faked.
  - Randomly marks ~50% of the newly-created dummy students' cycles Paid.

Then, for each of the last 7 days:
  - School-group students get a random on-time/late/absent mix, checked
    against the REAL configured school_start_time/grace period.
  - Academy-group students get a random present/absent mix, no
    punctuality judgment (matches real kiosk behavior for Academy scans).

Usage:
    docker compose exec api python scripts/seed_dummy_data.py
"""
import random
import sys
from datetime import time, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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

STUDENTS_PER_GROUP_PER_CLASS = 10  # bump this later to scale toward ~1,000
SCHOOL_MAX_ELIGIBLE_OFFSET = 12  # Class 10 -- matches the real fee-band ceiling

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


def _create_student(session: Session, class_level: ClassLevel, enrollment_year: int, admin_id: int) -> Student:
    roll_number = generate_roll_number(session, class_level_id=class_level.id, enrollment_year=enrollment_year)
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


def _enroll(session: Session, student: Student, category: FeeCategory, admin_id: int) -> None:
    session.add(Enrollment(
        student_id=student.id,
        category=category,
        discount_type=DiscountType.NONE,
        discount_value=None,
        status=EnrollmentStatus.ACTIVE,
        created_by_id=admin_id,
    ))


def seed_students(session: Session, admin_id: int) -> tuple[list[Student], list[Student]]:
    class_levels = session.exec(select(ClassLevel).order_by(ClassLevel.class_offset)).all()
    if not class_levels:
        raise RuntimeError("No ClassLevel rows found — run scripts/seed_reference_data.py first.")

    current_year = school_today().year
    school_group_students: list[Student] = []
    academy_group_students: list[Student] = []

    for class_level in class_levels:
        if class_level.class_offset <= SCHOOL_MAX_ELIGIBLE_OFFSET:
            for _ in range(STUDENTS_PER_GROUP_PER_CLASS):
                student = _create_student(session, class_level, current_year, admin_id)
                _enroll(session, student, FeeCategory.SCHOOL, admin_id)
                school_group_students.append(student)

        for _ in range(STUDENTS_PER_GROUP_PER_CLASS):
            student = _create_student(session, class_level, current_year, admin_id)
            academy_categories = [FeeCategory.COACHING, FeeCategory.ENGLISH, FeeCategory.COMPUTER]
            chosen = random.sample(academy_categories, k=random.choice([1, 1, 2]))  # mostly 1, sometimes 2
            for category in chosen:
                _enroll(session, student, category, admin_id)
            academy_group_students.append(student)

    session.commit()
    return school_group_students, academy_group_students


def seed_fee_cycles(session: Session, admin_id: int, dummy_students: list[Student]) -> None:
    today = school_today()
    period = f"{today.year:04d}-{today.month:02d}"

    # Reuses the REAL generation service -- same one the "Generate" button
    # calls -- so amounts are correctly banded, not hand-faked. This will
    # also generate cycles for any pre-existing real students who don't
    # have one yet for this period; that's correct, expected behavior of
    # the real service, not something this script should suppress.
    result = generate_fee_cycles(session, period=period, admin_id=admin_id)
    session.commit()
    print(f"Fee cycles generated for {period}: {result}")

    dummy_ids = {s.id for s in dummy_students}
    dummy_cycles = session.exec(
        select(FeeCycle).where(FeeCycle.period == period, FeeCycle.student_id.in_(dummy_ids))
    ).all()

    paid_count = 0
    for cycle in dummy_cycles:
        if random.random() < 0.5:
            cycle.status = FeeCycleStatus.PAID
            cycle.paid_date = today - timedelta(days=random.randint(0, 5))
            cycle.updated_by_id = admin_id
            session.add(cycle)
            paid_count += 1
    session.commit()
    print(f"Marked {paid_count} of {len(dummy_cycles)} dummy fee cycles as Paid (random ~50%).")


def _compute_punctuality(arrival: time, start_time: time, grace_minutes: int) -> PunctualityStatus:
    from datetime import date, datetime
    anchor = date(2000, 1, 1)
    cutoff = (datetime.combine(anchor, start_time) + timedelta(minutes=grace_minutes)).time()
    return PunctualityStatus.ON_TIME if arrival <= cutoff else PunctualityStatus.LATE


def seed_attendance(
    session: Session,
    school_group_students: list[Student],
    academy_group_students: list[Student],
) -> None:
    today = school_today()
    last_7_days = [today - timedelta(days=offset) for offset in range(6, -1, -1)]

    school_start = get_session_start_time(session, AttendanceSession.SCHOOL)
    school_grace = get_session_grace_minutes(session, AttendanceSession.SCHOOL)
    academy_start = get_session_start_time(session, AttendanceSession.ACADEMY)

    records_created = 0

    for student in school_group_students:
        for day in last_7_days:
            outcome = random.choices(
                ["on_time", "late", "absent"], weights=[60, 20, 20], k=1
            )[0]
            if outcome == "absent" or school_start is None:
                continue
            if outcome == "on_time":
                minutes_offset = random.randint(-30, school_grace)
            else:
                minutes_offset = random.randint(school_grace + 1, school_grace + 45)
            from datetime import date, datetime
            anchor = date(2000, 1, 1)
            arrival_dt = datetime.combine(anchor, school_start) + timedelta(minutes=minutes_offset)
            arrival_time = max(arrival_dt.time(), time(0, 1))
            punctuality = _compute_punctuality(arrival_time, school_start, school_grace)
            session.add(AttendanceRecord(
                student_id=student.id,
                scan_date=day,
                arrival_time=arrival_time,
                session=AttendanceSession.SCHOOL,
                punctuality_status=punctuality,
            ))
            records_created += 1

    for student in academy_group_students:
        for day in last_7_days:
            present = random.random() < 0.75
            if not present:
                continue
            base = academy_start or time(16, 0)
            from datetime import date, datetime
            anchor = date(2000, 1, 1)
            arrival_dt = datetime.combine(anchor, base) + timedelta(minutes=random.randint(-15, 90))
            arrival_time = max(arrival_dt.time(), time(0, 1))
            session.add(AttendanceRecord(
                student_id=student.id,
                scan_date=day,
                arrival_time=arrival_time,
                session=AttendanceSession.ACADEMY,
                punctuality_status=None,
            ))
            records_created += 1

    session.commit()
    print(f"Attendance records created: {records_created} (across last 7 days).")


def main() -> None:
    with Session(engine) as session:
        admin = session.exec(select(AdminUser)).first()
        if admin is None:
            print("No AdminUser found — create a super admin first (scripts/create_super_admin.py).")
            return

        total_school = 0
        total_academy = 0
        class_levels = session.exec(select(ClassLevel)).all()
        for cl in class_levels:
            if cl.class_offset <= SCHOOL_MAX_ELIGIBLE_OFFSET:
                total_school += STUDENTS_PER_GROUP_PER_CLASS
            total_academy += STUDENTS_PER_GROUP_PER_CLASS
        total = total_school + total_academy

        print(f"This will create {total} dummy students ({total_school} School-group, "
              f"{total_academy} Academy-group), plus fee cycles and 7 days of attendance for them.")
        print("This is NOT idempotent -- running it again adds another full batch.")
        confirm = input("Type 'yes' to continue: ").strip().lower()
        if confirm != "yes":
            print("Aborted -- nothing was created.")
            return

        school_group, academy_group = seed_students(session, admin.id)
        print(f"Students created: {len(school_group)} School-group, {len(academy_group)} Academy-group.")

        all_dummy = school_group + academy_group
        seed_fee_cycles(session, admin.id, all_dummy)
        seed_attendance(session, school_group, academy_group)

    print("Done.")


if __name__ == "__main__":
    main()
