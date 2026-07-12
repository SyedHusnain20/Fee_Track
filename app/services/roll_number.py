"""Roll-number generation — Section 6 of the spec.

Pulled forward from the nominal Step 8 slot because Student.roll_number is a
NOT NULL, unique column (set in Step 5's migration) — a Student row can't be
inserted without one. The QR *image* rendering (the `qrcode` library,
print-friendly display) genuinely stays Step 8; only this numeric algorithm
needed to move earlier.
"""
from sqlmodel import Session, select

from app.models.class_level import ClassLevel
from app.models.roll_number_counter import RollNumberCounter


def generate_roll_number(session: Session, class_level_id: int, enrollment_year: int) -> str:
    """cohort_code = (enrollment_year - class_offset) mod 100, then a
    3-digit atomically-incremented sequence within that cohort code.

    Call this inside the same session/transaction as the Student insert it's
    for, and commit promptly — the row lock from FOR UPDATE is held until
    that commit (or rollback).
    """
    class_level = session.get(ClassLevel, class_level_id)
    if class_level is None:
        raise ValueError(f"No ClassLevel with id={class_level_id}.")

    cohort_code = f"{(enrollment_year - class_level.class_offset) % 100:02d}"

    counter = session.exec(
        select(RollNumberCounter)
        .where(RollNumberCounter.cohort_code == cohort_code)
        .with_for_update()
    ).first()

    if counter is None:
        counter = RollNumberCounter(cohort_code=cohort_code, last_sequence=0)
        session.add(counter)
        session.flush()  # locks/persists it before the increment below

    if counter.last_sequence >= 999:
        raise ValueError(
            f"Cohort code {cohort_code} has reached 999 students — see the "
            "documented edge case in Section 6 of the spec."
        )

    counter.last_sequence += 1
    session.add(counter)
    session.flush()

    return f"{cohort_code}{counter.last_sequence:03d}"
