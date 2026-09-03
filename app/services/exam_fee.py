"""Exam fee — a one-off, School-only charge for a given period. See
app.models.exam_fee_setting for the storage model and its docstring for
the exact replace-not-add semantics on re-apply.

apply_exam_fee is the single entry point used by the "Apply" button on
the fee cycles page (app/api/fee_cycles.py). It does two things:

  1. Upserts the ExamFeeSetting row for the period, so any cycle
     generated for this period AFTER this call (via
     app.services.fee_cycle_generation) automatically picks up the new
     amount for School-enrolled students.
  2. Walks every FeeCycle that ALREADY exists for this period and belongs
     to a student with an active School enrollment, and rewrites its
     exam_fee/subtotal/total_due to reflect the new amount -- replacing
     whatever exam_fee that cycle had before (0, or a previous apply),
     never stacking on top of it.

A cycle that's already fully or partially PAID is still updated the same
way as an UNPAID one -- this call only touches total_due/subtotal/
exam_fee, never amount_paid or status, so raising a paid cycle's
total_due here can leave it needing a top-up payment, which is
surfaced the same way any other outstanding balance is (see
app.services.fee_payments). This wasn't separately confirmed, so if
already-settled cycles should be left alone instead, this is the one
place to change.
"""

from decimal import Decimal
from datetime import datetime

from sqlmodel import Session, select
from sqlalchemy import false

from app.models.enrollment import Enrollment
from app.models.enums import AuditAction, EnrollmentStatus, FeeCategory
from app.models.exam_fee_setting import ExamFeeSetting
from app.models.fee_cycle import FeeCycle
from app.services.audit import write_audit_log


def get_exam_fee_amount(session: Session, period: str) -> Decimal:
    row = session.get(ExamFeeSetting, period)
    return row.amount if row else Decimal("0.00")


def _school_student_ids(session: Session) -> set[int]:
    return set(
        session.exec(
            select(Enrollment.student_id).where(
                Enrollment.category == FeeCategory.SCHOOL,
                Enrollment.status == EnrollmentStatus.ACTIVE,
            )
        ).all()
    )


def apply_exam_fee(session: Session, period: str, amount: Decimal, admin_id: int) -> dict:
    """Does not commit -- caller commits once, matching
    generate_fee_cycles' pattern, so the setting row and every updated
    cycle land atomically. Returns {"updated_cycles"}."""
    setting = session.get(ExamFeeSetting, period)
    if setting:
        setting.amount = amount
        setting.updated_by_id = admin_id
        setting.updated_at = datetime.utcnow()
    else:
        setting = ExamFeeSetting(period=period, amount=amount, created_by_id=admin_id)
    session.add(setting)

    school_student_ids = _school_student_ids(session)
    cycles = session.exec(
        select(FeeCycle).where(
            FeeCycle.period == period,
            FeeCycle.student_id.in_(school_student_ids) if school_student_ids else false(),
        )
    ).all()

    updated = 0
    for cycle in cycles:
        if cycle.exam_fee == amount:
            continue
        before = {
            "exam_fee": float(cycle.exam_fee),
            "subtotal": float(cycle.subtotal),
            "total_due": float(cycle.total_due),
        }
        # Back out the old exam fee, apply the new one -- keeps
        # subtotal/total_due consistent (subtotal - discount == total_due)
        # regardless of how many times this period's amount changes.
        cycle.subtotal = cycle.subtotal - cycle.exam_fee + amount
        cycle.total_due = cycle.total_due - cycle.exam_fee + amount
        cycle.exam_fee = amount
        session.add(cycle)

        write_audit_log(
            session,
            admin_id=admin_id,
            action=AuditAction.UPDATE,
            entity_type="FeeCycle",
            entity_id=cycle.id,
            before_value=before,
            after_value={
                "exam_fee": float(cycle.exam_fee),
                "subtotal": float(cycle.subtotal),
                "total_due": float(cycle.total_due),
            },
        )
        updated += 1

    return {"updated_cycles": updated}
