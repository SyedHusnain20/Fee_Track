"""Discount used to live here (discount_type/discount_value per
student-category pairing) — moved to Student as a single overall discount
per student instead, applied once across all of a student's active
enrollments. See app.models.student and app.services.fees.

custom_fee is an optional per-enrollment override set once at enrollment
time (students/form.html's "Enroll in" checklist, or the detail page's
Add enrollment form). When null (the default -- left blank by the admin),
the enrollment is billed at whatever the category's band rate happens to
be at that student's current class level, same as before this field
existed. When set, it overrides the band rate for this enrollment only,
and stays fixed even if the band's default_amount changes later -- unlike
the band rate, which always re-prices live. See app.services.fees.
get_enrollment_amount, the only place this should be read from."""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, Index, text
from sqlmodel import Field, Relationship, SQLModel

from app.models._enum_utils import str_enum_type
from app.models.enums import EnrollmentStatus, FeeCategory

if TYPE_CHECKING:
    from app.models.student import Student


class Enrollment(SQLModel, table=True):
    __tablename__ = "enrollment"
    __table_args__ = (
        # A student can be re-enrolled in the same category after leaving it,
        # so this can't be a plain unique constraint on (student_id, category) —
        # it must only apply to the currently-active row.
        Index(
            "ix_enrollment_one_active_per_student_category",
            "student_id",
            "category",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    student_id: int = Field(foreign_key="student.id", index=True)
    category: FeeCategory = Field(
        sa_column=Column(str_enum_type(FeeCategory), nullable=False, index=True)
    )

    status: EnrollmentStatus = Field(
        default=EnrollmentStatus.ACTIVE,
        sa_column=Column(str_enum_type(EnrollmentStatus), nullable=False, index=True),
    )

    custom_fee: Optional[Decimal] = Field(default=None, max_digits=10, decimal_places=2)

    created_by_id: int = Field(foreign_key="admin_user.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_by_id: Optional[int] = Field(default=None, foreign_key="admin_user.id")
    updated_at: Optional[datetime] = Field(default=None)

    student: "Student" = Relationship(back_populates="enrollments")
