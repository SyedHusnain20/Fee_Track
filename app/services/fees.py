"""Fee computation — Section 5, updated for class-level-banded category
fees. Enrollment rows never store their own fee amount; it's always
looked up live from the current CategoryFeeDefault band matching the
student's class_offset, so a change to a band's fee ripples to every
enrolled student in that band instantly.
"""

from decimal import Decimal
from typing import Optional

from sqlmodel import Session, select

from app.models.category_fee_default import CategoryFeeDefault
from app.models.enrollment import Enrollment
from app.models.enums import DiscountType, EnrollmentStatus, FeeCategory
from app.models.student import Student

ZERO = Decimal("0.00")


def compute_enrollment_fee(
    default_amount: Decimal,
    discount_type: DiscountType,
    discount_value: Optional[Decimal],
) -> Decimal:
    """Unchanged — net fee given whatever band default_amount applies,
    minus its discount. Never negative."""
    if discount_type == DiscountType.NONE or discount_value is None:
        fee = default_amount
    elif discount_type == DiscountType.FIXED:
        fee = default_amount - discount_value
    elif discount_type == DiscountType.PERCENTAGE:
        fee = default_amount * (Decimal("100") - discount_value) / Decimal("100")
    else:
        fee = default_amount
    return fee if fee > ZERO else ZERO


def get_band_fee(session: Session, category: FeeCategory, class_offset: int) -> Optional[Decimal]:
    """Returns the default_amount for whichever band covers class_offset
    within this category, or None if no band covers it. A None result is
    also what enrollments.py's create_enrollment uses to reject an
    enrollment outright -- e.g. School's bands stop at offset 12 (Class
    10), so a Class 11 student gets None for category='school', and that
    enrollment is refused rather than silently charged Rs 0."""
    row = session.exec(
        select(CategoryFeeDefault).where(
            CategoryFeeDefault.category == category,
            CategoryFeeDefault.min_class_offset <= class_offset,
            CategoryFeeDefault.max_class_offset >= class_offset,
        )
    ).first()
    return row.default_amount if row else None


def compute_student_total_fee(session: Session, student_id: int) -> Decimal:
    """Sum of compute_enrollment_fee() across a student's active
    enrollments, each looked up against the band matching the student's
    current class level. An enrollment whose category has no matching
    band for this student's class level is skipped (contributes 0) rather
    than raising -- this function also backs FeeCycle generation and
    shouldn't crash a live billing run over one bad row."""
    student = session.get(Student, student_id)
    if student is None:
        return ZERO
    class_offset = student.class_level.class_offset

    active_enrollments = session.exec(
        select(Enrollment).where(
            Enrollment.student_id == student_id,
            Enrollment.status == EnrollmentStatus.ACTIVE,
        )
    ).all()

    total = ZERO
    for enrollment in active_enrollments:
        default_amount = get_band_fee(session, enrollment.category, class_offset)
        if default_amount is None:
            continue
        total += compute_enrollment_fee(
            default_amount, enrollment.discount_type, enrollment.discount_value
        )
    return total
