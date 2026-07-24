"""Teacher staff-ID generation — auto-numbered as 0001, 0002, ... on
teacher creation, replacing the previous manual-entry field.

Derived directly from existing Teacher rows (MAX of numeric staff_ids + 1)
rather than a dedicated counter table: teacher creation is low-frequency
and effectively single-admin-at-a-time on this deployment, and
Teacher.staff_id already has a unique constraint that fails loudly
(IntegrityError) on the rare concurrent-collision case rather than
silently corrupting data — acceptable at this scale, unlike Student.
roll_number's cohort-based counter scheme, which genuinely needs atomic
counter rows because it's a code parents/staff pull out to double-check
by hand (Section 6).

Any existing teacher with a non-numeric staff_id (assigned manually
before this change) is left untouched and simply ignored when computing
the next number — this only affects new teachers created going forward.
"""
from sqlmodel import Session, select

from app.models.teacher import Teacher


def generate_staff_id(session: Session) -> str:
    existing_ids = session.exec(select(Teacher.staff_id)).all()
    numeric_ids = [int(sid) for sid in existing_ids if sid.isdigit()]
    next_number = (max(numeric_ids) + 1) if numeric_ids else 1
    return f"{next_number:04d}"
