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

Since migration c58e0d3a9f16, every field of compute_student_fee_breakdown()
gets snapshotted onto the FeeCycle row, not just the bottom-line total —
category_breakdown, subtotal, discount_type/value/amount all freeze at
generation time alongside total_due, for the itemized invoice.

Exam fee (see app.services.exam_fee): if an exam fee has been applied for
this period and the student has an active School enrollment, it's folded
into subtotal/total_due here too, at generation time — a student whose
cycle didn't exist yet when "Apply exam fee" was clicked still gets it
the moment their cycle is generated, same as one whose cycle already
existed.

Per Key Design Principle #7, every row created here writes through the
audit-log hook.
"""

import re
from decimal import Decimal

from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from app.models.enums import AuditAction, FeeCategory, FeeCycleStatus
from app.models.fee_cycle import FeeCycle
from app.models.student import Student
from app.services.audit import write_audit_log
from app.services.exam_fee import get_exam_fee_amount
from app.services.fees import compute_fee_breakdowns_bulk

PERIOD_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def generate_fee_cycles(session: Session, period: str, admin_id: int) -> dict:
    """Does not commit — caller commits once, so the whole batch (all
    created FeeCycle rows plus their audit entries) lands atomically.
    Returns {"created", "skipped_existing", "skipped_zero_due"}.
    """
    if not PERIOD_PATTERN.match(period):
        raise ValueError('Period must be in "YYYY-MM" format, e.g. "2026-07".')

    # selectinload(Student.class_level): same reason as students.py's list
    # route — without it, compute_fee_breakdowns_bulk's
    # student.class_level.class_offset lazy-loads one row at a time.
    students = session.exec(
        select(Student)
        .where(Student.is_active.is_(True))
        .options(selectinload(Student.class_level))
    ).all()

    already_generated = set(
        session.exec(select(FeeCycle.student_id).where(FeeCycle.period == period)).all()
    )

    # Was: compute_student_fee_breakdown(session, student) called once per
    # student in the loop below — each call re-querying every
    # CategoryFeeDefault band plus that student's own enrollments, on top
    # of the class_level lazy-load above. For a real school that's
    # roughly (1 + up to 4) x active-student-count queries on every
    # monthly run. Computed in bulk up front instead — same breakdowns,
    # a small fixed number of queries total regardless of student count.
    breakdowns = compute_fee_breakdowns_bulk(session, students)
    exam_fee_amount = get_exam_fee_amount(session, period)

    created = 0
    skipped_existing = 0
    skipped_zero_due = 0

    for student in students:
        if student.id in already_generated:
            skipped_existing += 1
            continue

        breakdown = breakdowns[student.id]
        is_school_student = FeeCategory.SCHOOL in breakdown["category_amounts"]
        exam_fee = exam_fee_amount if (is_school_student and exam_fee_amount > 0) else Decimal("0.00")

        subtotal = breakdown["subtotal"] + exam_fee
        total_due = breakdown["final_total"] + exam_fee
        if total_due <= Decimal("0.00"):
            skipped_zero_due += 1
            continue

        cycle = FeeCycle(
            student_id=student.id,
            period=period,
            total_due=total_due,
            subtotal=subtotal,
            discount_type=breakdown["discount_type"],
            discount_value=breakdown["discount_value"],
            discount_amount=breakdown["discount_amount"],
            exam_fee=exam_fee,
            category_breakdown={
                category.value: str(amount)
                for category, amount in breakdown["category_amounts"].items()
            },
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
                "subtotal": float(cycle.subtotal),
                "discount_type": cycle.discount_type.value,
                "discount_amount": float(cycle.discount_amount),
                "exam_fee": float(cycle.exam_fee),
                "category_breakdown": cycle.category_breakdown,
                "status": cycle.status.value,
            },
        )
        created += 1

    return {
        "created": created,
        "skipped_existing": skipped_existing,
        "skipped_zero_due": skipped_zero_due,
    }
