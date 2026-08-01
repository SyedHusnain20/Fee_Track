"""Fee computation — Section 5, updated for class-level-banded category
fees, again for the move from per-enrollment discounts to a single
overall discount per student, and again for the optional per-enrollment
custom_fee override. By default an enrollment still has no fee of its
own — it's looked up live from the current CategoryFeeDefault band
matching the student's class_offset, so a change to a band's fee ripples
to every enrolled student in that band instantly. An admin can instead
set Enrollment.custom_fee once at enrollment time (students/form.html's
checklist, or the detail page's Add enrollment form); when set, it
overrides the band rate for that one enrollment and stays fixed even if
the band's default_amount later changes -- see get_enrollment_amount,
the only place this should be read from.

Discount now applies exactly once, to a student's combined total across
all active enrollments (Student.discount_type/discount_value) — not
separately per category as it used to (that lived on Enrollment.discount_*
until migration a3f9c81b2d47 moved it here). This changes what "the fee
for category X" means: get_band_fee() still returns each category's raw,
undiscounted band rate — the discount is only ever visible in the
combined total, never attributed to one category over another.
"""

from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlmodel import Session, select

from app.models.category_fee_default import CategoryFeeDefault
from app.models.enrollment import Enrollment
from app.models.enums import DiscountType, EnrollmentStatus, FeeCategory
from app.models.student import Student

ZERO = Decimal("0.00")


def apply_discount(
    amount: Decimal,
    discount_type: DiscountType,
    discount_value: Optional[Decimal],
) -> Decimal:
    """Net amount after applying a discount. Never negative. Same discount
    math as the old per-enrollment version, just applied once to a
    student's combined fee total now rather than separately per
    enrollment/category."""
    if discount_type == DiscountType.NONE or discount_value is None:
        result = amount
    elif discount_type == DiscountType.FIXED:
        result = amount - discount_value
    elif discount_type == DiscountType.PERCENTAGE:
        result = amount * (Decimal("100") - discount_value) / Decimal("100")
    else:
        result = amount
    return result if result > ZERO else ZERO


def parse_discount_input(discount_type: DiscountType, discount_value_raw: str) -> Optional[Decimal]:
    """None for DiscountType.NONE, otherwise a validated Decimal. Raises
    ValueError with a message safe to show directly to the admin. Same
    validation app/api/enrollments.py used to do per-enrollment; now used
    once, at student add/edit time, in app/api/students.py."""
    if discount_type == DiscountType.NONE:
        return None

    if not discount_value_raw.strip():
        raise ValueError("Enter a discount value for a fixed or percentage discount.")

    try:
        value = Decimal(discount_value_raw)
    except InvalidOperation:
        raise ValueError("Discount value must be a number.")

    if value < 0:
        raise ValueError("Discount value can't be negative.")
    if discount_type == DiscountType.PERCENTAGE and value > 100:
        raise ValueError("A percentage discount can't exceed 100.")

    return value


def get_band_fee(session: Session, category: FeeCategory, class_offset: int) -> Optional[Decimal]:
    """Returns the default_amount for whichever band covers class_offset
    within this category, or None if no band covers it. A None result is
    also what enrollments.py's create_enrollment uses to reject an
    enrollment outright -- e.g. School's bands stop at offset 12 (Class
    10), so a Class 11 student gets None for category='school', and that
    enrollment is refused rather than silently charged Rs 0.

    This is the RAW band rate — no discount applied here, and no
    per-enrollment custom_fee override either (see get_enrollment_amount
    below for the version that checks that first). Discount only ever
    applies once, to the combined total (see
    compute_student_fee_breakdown).
    """
    row = session.exec(
        select(CategoryFeeDefault).where(
            CategoryFeeDefault.category == category,
            CategoryFeeDefault.min_class_offset <= class_offset,
            CategoryFeeDefault.max_class_offset >= class_offset,
        )
    ).first()
    return row.default_amount if row else None


def get_enrollment_amount(
    session: Session, enrollment: Enrollment, class_offset: int
) -> Optional[Decimal]:
    """The amount actually charged for one enrollment: its own custom_fee
    if the admin set one at enrollment time, otherwise the current band
    rate for its category at class_offset (get_band_fee). Returns None
    under the same condition get_band_fee does -- no custom_fee AND no
    band covers this class_offset -- which should only come up if a
    student's class level changed after they enrolled, since enrollment
    itself refuses categories with no covering band.
    """
    if enrollment.custom_fee is not None:
        return enrollment.custom_fee
    return get_band_fee(session, enrollment.category, class_offset)


def compute_student_fee_breakdown(session: Session, student: Student) -> dict:
    """Full breakdown for a student's active enrollments, each priced at
    the current band rate for their class level, with the student's
    single overall discount applied once to the combined subtotal.

    Takes a Student object (not student_id) since callers generally
    already have it loaded — avoids a redundant lookup. Use
    compute_student_total_fee() below if all you have is an id.

    Returns:
        category_amounts: {FeeCategory: Decimal} — raw, undiscounted
            per-category amounts, only for categories the student is
            actively enrolled in and which have a matching band.
        subtotal: sum of category_amounts.values()
        discount_type / discount_value: the student's own settings, as-is
        discount_amount: subtotal - final_total (always >= 0)
        final_total: subtotal after the discount, never negative

    Powers the Students list Total Fee column, the student detail page's
    fee breakdown, FeeCycle generation (final_total becomes the
    snapshotted total_due), and — from Phase 3 on — the itemized invoice.
    """
    class_offset = student.class_level.class_offset

    active_enrollments = session.exec(
        select(Enrollment).where(
            Enrollment.student_id == student.id,
            Enrollment.status == EnrollmentStatus.ACTIVE,
        )
    ).all()

    category_amounts: dict = {}
    subtotal = ZERO
    for enrollment in active_enrollments:
        amount = get_enrollment_amount(session, enrollment, class_offset)
        if amount is None:
            continue
        category_amounts[enrollment.category] = amount
        subtotal += amount

    final_total = apply_discount(subtotal, student.discount_type, student.discount_value)
    discount_amount = subtotal - final_total

    return {
        "category_amounts": category_amounts,
        "subtotal": subtotal,
        "discount_type": student.discount_type,
        "discount_value": student.discount_value,
        "discount_amount": discount_amount,
        "final_total": final_total,
    }


def compute_student_total_fee(session: Session, student_id: int) -> Decimal:
    """Thin wrapper over compute_student_fee_breakdown() for callers that
    only have a student_id and only need the bottom-line number — FeeCycle
    generation."""
    student = session.get(Student, student_id)
    if student is None:
        return ZERO
    return compute_student_fee_breakdown(session, student)["final_total"]
