"""Due-carry-forward payment recording — the "click Pay, type an amount"
flow described for the fee cycles page.

record_payment() is the single entry point. Given the cycle the admin
clicked Pay on (the "anchor" — always the most recent period being
viewed) and an amount, it:

  1. Builds the "outstanding queue": every one of that student's FeeCycle
     rows with period <= anchor.period and status != PAID, oldest period
     first. This always includes the anchor cycle itself (unless it's
     already fully PAID, which is rejected below) and any older
     UNPAID/PARTIAL cycles — i.e. the carried-forward due.
  2. Validates the amount: must be positive and can't exceed the total
     outstanding across the whole queue (no overpayment/advance-payment
     support — money in excess of what's owed is rejected with an error
     rather than silently applied to a future month that doesn't exist
     yet).
  3. Applies the amount FIFO, oldest cycle first: each cycle absorbs up
     to its own remaining balance (total_due - amount_paid) before any
     money moves to the next one. A cycle that's fully absorbed becomes
     PAID (paid_date/collected_by set); a cycle that gets some but not
     all of its remaining balance becomes PARTIAL.
  4. Writes one FeePayment row summarizing the transaction: the
     previous-due amount/month-count (everything in the queue strictly
     before the anchor, as it stood at the moment of payment), the
     anchor's own due, the amount just paid, and what's left owing
     afterward.

Does not commit -- caller commits once, matching this codebase's other
bulk-write services (generate_fee_cycles, apply_exam_fee).
"""

from datetime import datetime
from decimal import Decimal

from sqlmodel import Session, select

from app.core.timezone import school_today
from app.models.enums import AuditAction, FeeCycleStatus
from app.models.fee_cycle import FeeCycle
from app.models.fee_payment import FeePayment
from app.services.audit import write_audit_log


class PaymentError(ValueError):
    """Raised for any invalid payment amount — caller (the API route)
    turns this into a user-facing form error rather than a 500."""


def _outstanding_queue(session: Session, anchor: FeeCycle) -> list[FeeCycle]:
    return session.exec(
        select(FeeCycle)
        .where(
            FeeCycle.student_id == anchor.student_id,
            FeeCycle.period <= anchor.period,
            FeeCycle.status != FeeCycleStatus.PAID,
        )
        .order_by(FeeCycle.period.asc())
    ).all()


def get_outstanding_summary(session: Session, anchor: FeeCycle) -> dict:
    """Read-only preview of what a payment against this cycle would look
    like -- used to pre-fill the payment popup with the previous-due
    breakdown before the admin types an amount. Mirrors the numbers
    record_payment() below would use, without touching anything."""
    queue = _outstanding_queue(session, anchor)
    previous = [c for c in queue if c.period < anchor.period]
    previous_due_amount = sum((c.total_due - c.amount_paid for c in previous), Decimal("0.00"))
    current_month_due = anchor.total_due - anchor.amount_paid
    return {
        "previous_due_amount": previous_due_amount,
        "previous_due_months": len(previous),
        "current_month_due": current_month_due,
        "total_outstanding": previous_due_amount + current_month_due,
    }


def record_payment(
    session: Session, cycle_id: int, amount: Decimal, admin_id: int
) -> FeePayment:
    anchor = session.get(FeeCycle, cycle_id)
    if not anchor:
        raise PaymentError("Fee cycle not found.")
    if anchor.status == FeeCycleStatus.PAID:
        raise PaymentError("This cycle is already fully paid.")
    if amount <= Decimal("0.00"):
        raise PaymentError("Enter an amount greater than zero.")

    queue = _outstanding_queue(session, anchor)
    summary = get_outstanding_summary(session, anchor)
    total_outstanding = summary["total_outstanding"]

    if amount > total_outstanding:
        raise PaymentError(
            f"That's more than the Rs {total_outstanding:.2f} currently owed "
            "across this and any carried-forward months."
        )

    today = school_today()
    remaining_to_apply = amount

    for cycle in queue:
        if remaining_to_apply <= Decimal("0.00"):
            break
        cycle_remaining = cycle.total_due - cycle.amount_paid
        if cycle_remaining <= Decimal("0.00"):
            continue

        pay_amount = min(remaining_to_apply, cycle_remaining)
        before = {
            "amount_paid": float(cycle.amount_paid),
            "status": cycle.status.value,
        }
        cycle.amount_paid += pay_amount
        remaining_to_apply -= pay_amount

        if cycle.amount_paid >= cycle.total_due:
            cycle.status = FeeCycleStatus.PAID
            cycle.paid_date = today
            cycle.collected_by_id = admin_id
        else:
            cycle.status = FeeCycleStatus.PARTIAL

        cycle.updated_by_id = admin_id
        cycle.updated_at = datetime.utcnow()
        session.add(cycle)

        write_audit_log(
            session,
            admin_id=admin_id,
            action=AuditAction.UPDATE,
            entity_type="FeeCycle",
            entity_id=cycle.id,
            before_value=before,
            after_value={
                "amount_paid": float(cycle.amount_paid),
                "status": cycle.status.value,
            },
        )

    payment = FeePayment(
        student_id=anchor.student_id,
        anchor_cycle_id=anchor.id,
        previous_due_amount=summary["previous_due_amount"],
        previous_due_months=summary["previous_due_months"],
        current_month_due=summary["current_month_due"],
        amount_paid=amount,
        remaining_due=total_outstanding - amount,
        created_by_id=admin_id,
    )
    session.add(payment)
    session.flush()  # need payment.id for the receipt redirect
    return payment
