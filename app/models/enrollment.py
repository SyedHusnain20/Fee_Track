from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, Index, text
from sqlmodel import Field, Relationship, SQLModel

from app.models._enum_utils import str_enum_type
from app.models.enums import DiscountType, EnrollmentStatus, FeeCategory

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
    
    discount_type: DiscountType = Field(
        default=DiscountType.NONE,
        sa_column=Column(str_enum_type(DiscountType), nullable=False),
    )
    discount_value: Optional[Decimal] = Field(default=None, max_digits=10, decimal_places=2)
    status: EnrollmentStatus = Field(
        default=EnrollmentStatus.ACTIVE,
        sa_column=Column(str_enum_type(EnrollmentStatus), nullable=False, index=True),
    )

    created_by_id: int = Field(foreign_key="admin_user.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_by_id: Optional[int] = Field(default=None, foreign_key="admin_user.id")
    updated_at: Optional[datetime] = Field(default=None)

    student: "Student" = Relationship(back_populates="enrollments")
