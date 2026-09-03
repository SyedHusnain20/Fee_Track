"""One-off data fix for students an earlier test run of /rollover already
promoted past the school's real ceiling (see SCHOOL_CEILING_NAME in
app/api/rollover.py — the school ends at Class 10; ClassLevel rows above
that exist only for Academy). This script does NOT change behavior going
forward — rollover.py's own fix handles that. This just repairs rows that
were already pushed into "Class 11"/"Class 12" before that fix existed.

For every currently-active student sitting above Class 10:
  - class_level_id is moved back to Class 10 (their real, last legitimate
    level) — this is what makes their fee band resolve correctly again;
    left at "Class 11" it matches no SCHOOL band and prices at Rs 0.
  - is_active is set to False (graduating), same as rollover does for a
    Class 10 student today.
  - Both changes are audit-logged, same as rollover's own writes.

Data (Enrollment, FeeCycle, attendance history) is untouched — same scope
guarantee as rollover.py itself. No future FeeCycle rows will be generated
for them once is_active is False (generate_fee_cycles only looks at active
students), and they drop out of active-student / revenue counts without
losing their history.

Safe to re-run: only touches active students still above Class 10, so a
second run finds nothing left to do.

Usage:
    docker compose exec api python scripts/fix_class10_ceiling_rollover.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select

from app.api.rollover import SCHOOL_CEILING_NAME
from app.core.database import engine
from app.models.class_level import ClassLevel
from app.models.enums import AuditAction
from app.models.student import Student
from app.services.audit import write_audit_log

# Attributed to no specific admin (this is a script run, not a UI action).
# write_audit_log requires an admin_id FK, so this uses id 1 (the first
# super admin, created by scripts/create_super_admin.py) purely as the
# audit trail's "who" — adjust if that's not accurate for your DB.
SCRIPT_ADMIN_ID = 1


def main() -> None:
    with Session(engine) as session:
        ceiling = session.exec(
            select(ClassLevel).where(ClassLevel.name == SCHOOL_CEILING_NAME)
        ).first()
        if ceiling is None:
            print(f"No ClassLevel named {SCHOOL_CEILING_NAME!r} found — nothing to do.")
            return

        above_ceiling_ids = [
            cl.id
            for cl in session.exec(
                select(ClassLevel).where(ClassLevel.class_offset > ceiling.class_offset)
            ).all()
        ]
        if not above_ceiling_ids:
            print("No ClassLevel rows above the school ceiling — nothing to do.")
            return

        students = session.exec(
            select(Student).where(
                Student.class_level_id.in_(above_ceiling_ids),
                Student.is_active == True,  # noqa: E712
            )
        ).all()

        if not students:
            print("No active students above the school ceiling — nothing to fix.")
            return

        for student in students:
            before = {
                "class_level_id": student.class_level_id,
                "is_active": student.is_active,
            }
            student.class_level_id = ceiling.id
            student.is_active = False
            session.add(student)
            write_audit_log(
                session,
                admin_id=SCRIPT_ADMIN_ID,
                action=AuditAction.UPDATE,
                entity_type="Student",
                entity_id=student.id,
                before_value=before,
                after_value={"class_level_id": ceiling.id, "is_active": False},
            )

        session.commit()
        print(f"Fixed {len(students)} student(s): moved back to {SCHOOL_CEILING_NAME} and deactivated.")


if __name__ == "__main__":
    main()
