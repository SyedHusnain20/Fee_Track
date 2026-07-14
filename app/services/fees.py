"""Fee computation — Section 5 of the spec.

Enrollment rows never store their own fee amount; it's always looked up
live from the current CategoryFeeDefault, so a change to a category default
ripples to every enrolled student instantly with no per-row updates needed.
"""
from decimal import Decimal
from typing import Optional

from sqlmodel import Session, select

from app.models.category_fee_default import CategoryFeeDefault
from app.models.enrollment import Enrollment
from app.models.enums import DiscountType, EnrollmentStatus

ZERO = Decimal("0.00")


def compute_enrollment_fee(
    default_amount: Decimal,
    discount_type: DiscountType,
    discount_value: Optional[Decimal],
) -> Decimal:
    """Net fee for one enrollment: category default, minus its discount.
    Never returns negative — a fixed discount larger than a (possibly
    later-lowered) default just floors at 0, it doesn't go negative.
    """
    if discount_type == DiscountType.NONE or discount_value is None:
        fee = default_amount
    elif discount_type == DiscountType.FIXED:
        fee = default_amount - discount_value
    elif discount_type == DiscountType.PERCENTAGE:
        fee = default_amount * (Decimal("100") - discount_value) / Decimal("100")
    else:
        fee = default_amount

    return fee if fee > ZERO else ZERO


def compute_student_total_fee(session: Session, student_id: int) -> Decimal:
    """Sum of compute_enrollment_fee() across a student's active
    enrollments only — Section 5: "Student's total fee = sum across active
    enrollments of (current category default, net of discount)." Used by
    FeeCycle generation to snapshot total_due at generation time.
    """
    active_enrollments = session.exec(
        select(Enrollment).where(
            Enrollment.student_id == student_id,
            Enrollment.status == EnrollmentStatus.ACTIVE,
        )
    ).all()
    category_defaults = {
        row.category: row.default_amount for row in session.exec(select(CategoryFeeDefault)).all()
    }

    total = ZERO
    for enrollment in active_enrollments:
        default_amount = category_defaults.get(enrollment.category, ZERO)
        total += compute_enrollment_fee(default_amount, enrollment.discount_type, enrollment.discount_value)
    return total
