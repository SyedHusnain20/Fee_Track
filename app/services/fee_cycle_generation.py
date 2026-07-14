"""FeeCycle bulk generation — Section 5: "Full monthly fee history kept via
FeeCycle — total_due snapshotted at generation time; later default changes
don't retroactively rewrite past bills."

Generation runs per period (e.g. "2026-07") across every active student.
Students who already have a cycle for that period are skipped (the
(student_id, period) unique constraint from Step 5's migration would also
catch this, but checking first avoids relying on catching an
IntegrityError for what's actually the common, expected case on a re-run).
Students with zero active enrollments (total_due == 0) are skipped too —
nothing meaningful to bill.

Per Key Design Principle #7, every row created here writes through the
audit-log hook.
"""
import re
from decimal import Decimal

from sqlmodel import Session, select

from app.models.enums import AuditAction, FeeCycleStatus
from app.models.fee_cycle import FeeCycle
from app.models.student import Student
from app.services.audit import write_audit_log
from app.services.fees import compute_student_total_fee

PERIOD_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def generate_fee_cycles(session: Session, period: str, admin_id: int) -> dict:
    """Does not commit — caller commits once, so the whole batch (all
    created FeeCycle rows plus their audit entries) lands atomically.
    Returns {"created", "skipped_existing", "skipped_zero_due"}.
    """
    if not PERIOD_PATTERN.match(period):
        raise ValueError('Period must be in "YYYY-MM" format, e.g. "2026-07".')

    students = session.exec(select(Student).where(Student.is_active.is_(True))).all()

    already_generated = set(
        session.exec(select(FeeCycle.student_id).where(FeeCycle.period == period)).all()
    )

    created = 0
    skipped_existing = 0
    skipped_zero_due = 0

    for student in students:
        if student.id in already_generated:
            skipped_existing += 1
            continue

        total_due = compute_student_total_fee(session, student.id)
        if total_due <= Decimal("0.00"):
            skipped_zero_due += 1
            continue

        cycle = FeeCycle(
            student_id=student.id,
            period=period,
            total_due=total_due,
            status=FeeCycleStatus.UNPAID,
            created_by_id=admin_id,
        )
        session.add(cycle)
        session.flush()  # need cycle.id for the audit entry below

        write_audit_log(
            session,
            admin_id=admin_id,
            action=AuditAction.CREATE,
            entity_type="FeeCycle",
            entity_id=cycle.id,
            before_value=None,
            after_value={
                "student_id": cycle.student_id,
                "period": cycle.period,
                "total_due": float(cycle.total_due),
                "status": cycle.status.value,
            },
        )
        created += 1

    return {"created": created, "skipped_existing": skipped_existing, "skipped_zero_due": skipped_zero_due}
