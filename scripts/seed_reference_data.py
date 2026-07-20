"""One-off seed script for fixed reference data: the 15 ClassLevel rows, 4
CategoryFeeDefault rows, and attendance timing settings — updated for the
School/Academy kiosk redesign. Billing (FeeCategory, 4 values) is untouched
by this redesign; only the kiosk-side AttendanceSession timing keys changed.

Neither Step 5 nor Step 6 populated ClassLevel/CategoryFeeDefault — Student
creation (Step 7) hard-depends on ClassLevel existing via a foreign key, and
Enrollment depends on CategoryFeeDefault the same way. The kiosk needs
per-session start_time (and, for School only, grace_minutes) SystemSetting
rows to compute on-time/late — seeded here with PLACEHOLDER values (not
your school's real schedule; review and correct them on the /settings page).

Safe to re-run: skips rows/keys that already exist rather than erroring on
unique constraints. NOTE: this script does NOT delete the old per-category
(coaching_start_time, coaching_grace_minutes, english_*, computer_*) keys
left over from before the redesign — that cleanup belongs in the migration.

Usage:
    docker compose exec api python scripts/seed_reference_data.py
"""
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select

from app.core.database import engine
from app.models.category_fee_default import CategoryFeeDefault
from app.models.class_level import ClassLevel
from app.models.enums import AttendanceSession, FeeCategory
from app.models.system_setting import SystemSetting

# Section 6: Foundation 1-3 -> offsets 0-2, Class 1-12 -> offsets 3-14.
CLASS_LEVELS = [
    ("Foundation 1", 0),
    ("Foundation 2", 1),
    ("Foundation 3", 2),
] + [(f"Class {n}", n + 2) for n in range(1, 13)]

DEFAULT_FEE = Decimal("1000.00")  # Section 5: "starts at Rs 1,000, admin-editable"

# PLACEHOLDER schedule — staggered guesses so the kiosk is functional out of
# the box, not a real school timetable. Review on /settings before go-live.
# Academy has no grace_minutes key: there's no late calculation for it, so
# a grace period is meaningless — its start_time is reference/reporting-only.
DEFAULT_SESSION_TIMING = {
    AttendanceSession.SCHOOL: {"start_time": "08:00", "grace_minutes": 15},
    AttendanceSession.ACADEMY: {"start_time": "16:00"},
}

ACADEMIC_YEAR_RESET_MONTH = "4"  # Section 4: "default April" — Step 11 reads this


def seed_class_levels(session: Session) -> None:
    existing = {cl.class_offset for cl in session.exec(select(ClassLevel)).all()}
    added = 0
    for name, offset in CLASS_LEVELS:
        if offset in existing:
            continue
        session.add(ClassLevel(name=name, class_offset=offset))
        added += 1
    print(f"ClassLevel: added {added}, skipped {len(CLASS_LEVELS) - added} already present")


def seed_category_fee_defaults(session: Session) -> None:
    existing = {c.category for c in session.exec(select(CategoryFeeDefault)).all()}
    added = 0
    for category in FeeCategory:
        if category in existing:
            continue
        session.add(CategoryFeeDefault(category=category, default_amount=DEFAULT_FEE))
        added += 1
    print(
        f"CategoryFeeDefault: added {added}, "
        f"skipped {len(list(FeeCategory)) - added} already present"
    )


def seed_attendance_settings(session: Session) -> None:
    existing_keys = {row.key for row in session.exec(select(SystemSetting)).all()}
    added = 0

    for attendance_session, timing in DEFAULT_SESSION_TIMING.items():
        start_key = f"{attendance_session.value}_start_time"
        if start_key not in existing_keys:
            session.add(SystemSetting(key=start_key, value=timing["start_time"]))
            added += 1
        if "grace_minutes" in timing:
            grace_key = f"{attendance_session.value}_grace_minutes"
            if grace_key not in existing_keys:
                session.add(SystemSetting(key=grace_key, value=str(timing["grace_minutes"])))
                added += 1

    if "academic_year_reset_month" not in existing_keys:
        session.add(SystemSetting(key="academic_year_reset_month", value=ACADEMIC_YEAR_RESET_MONTH))
        added += 1

    print(f"SystemSetting: added {added} attendance/academic-year keys (skipped any already present)")


def main() -> None:
    with Session(engine) as session:
        seed_class_levels(session)
        seed_category_fee_defaults(session)
        seed_attendance_settings(session)
        session.commit()
    print("Seed complete.")


if __name__ == "__main__":
    main()