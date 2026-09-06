"""Backdated due entry — for a newly-created student who already owed
money before being added to Fee Track (e.g. migrating from paper
records). An admin enters a total amount and a number of months on the
create-student form; this seeds that as real, ordinary FeeCycle rows for
the most recent N months, all UNPAID, so the existing due-carry-forward
payment flow (app.services.fee_payments) picks them up exactly the same
way it would for any other unpaid history — same "Pay" button, same FIFO
oldest-first allocation, same previous-due display. No separate code path
for "old" vs "system-generated" due.

Months always end at the CURRENT period and count backward -- entering
"7000 due, 7 months" today (September) creates one cycle each for March
through September. The total is split evenly across the months (any
leftover paisa from an uneven division goes on the most recent month), not
computed from the student's actual enrollments/bands -- this is a manual
catch-up figure the admin is entering directly, not something to
recompute from category rules that may not even reflect what the student
was actually enrolled in back then.

Each row's category_breakdown is left as None (same as any FeeCycle
generated before that field existed -- see app/models/fee_cycle.py) so
the invoice/receipt templates fall back to a plain "Fee for <period>"
line automatically, without needing a special case for these rows.
"""

from datetime import date
from decimal import ROUND_DOWN, Decimal

from sqlmodel import Session

from app.models.enums import AuditAction, DiscountType, FeeCycleStatus
from app.models.fee_cycle import FeeCycle
from app.models.student import Student
from app.services.audit import write_audit_log


def _recent_periods_ending_at(year: int, month: int, count: int) -> list[str]:
    """count "YYYY-MM" strings ending at (year, month) inclusive, oldest
    first -- e.g. (2026, 9, 7) -> ["2026-03", ..., "2026-09"]."""
    periods = []
    y, m = year, month
    for _ in range(count):
        periods.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    periods.reverse()
    return periods


def create_backdated_fee_cycles(
    session: Session,
    student: Student,
    total_due: Decimal,
    num_months: int,
    admin_id: int,
    as_of: date,
) -> list[FeeCycle]:
    """Does not commit -- caller commits once, same convention as
    generate_fee_cycles/apply_exam_fee. Returns the created rows."""
    periods = _recent_periods_ending_at(as_of.year, as_of.month, num_months)

    # Split evenly; whatever doesn't divide cleanly (e.g. Rs 1000 over 3
    # months) lands on the LAST period rather than being lost to rounding
    # -- the sum across all created rows always equals total_due exactly.
    per_month = (total_due / num_months).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    amounts = [per_month] * (num_months - 1)
    amounts.append(total_due - per_month * (num_months - 1))

    created = []
    for period, amount in zip(periods, amounts):
        cycle = FeeCycle(
            student_id=student.id,
            period=period,
            total_due=amount,
            subtotal=amount,
            discount_type=DiscountType.NONE,
            discount_value=None,
            discount_amount=Decimal("0.00"),
            category_breakdown=None,
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
                "note": "backdated due entered at student creation",
            },
        )
        created.append(cycle)

    return created
