from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Column
from sqlmodel import Field, Relationship, SQLModel

from app.models._enum_utils import str_enum_type
from app.models.enums import DiscountType

if TYPE_CHECKING:
    from app.models.attendance_record import AttendanceRecord
    from app.models.class_level import ClassLevel
    from app.models.enrollment import Enrollment
    from app.models.fee_cycle import FeeCycle


class Student(SQLModel, table=True):
    __tablename__ = "student"

    id: Optional[int] = Field(default=None, primary_key=True)
    roll_number: str = Field(max_length=5, unique=True, index=True)
    name: str = Field(max_length=150)
    father_name: str = Field(max_length=150)
    parent_whatsapp: str = Field(max_length=20)
    qr_code: str = Field(unique=True, index=True)
    class_level_id: int = Field(foreign_key="class_level.id", index=True)
    is_active: bool = Field(default=True)

    # One overall discount per student, set at student-add time (or later
    # via edit) and applied once to the combined total across all of a
    # student's active enrollments — not separately per category as it
    # used to be. Previously this lived on Enrollment (one discount per
    # student-category pairing); moved here so a student has exactly one
    # discount regardless of how many categories they're enrolled in. See
    # app.services.fees.
    discount_type: DiscountType = Field(
        default=DiscountType.NONE,
        sa_column=Column(str_enum_type(DiscountType), nullable=False),
    )
    discount_value: Optional[Decimal] = Field(default=None, max_digits=10, decimal_places=2)

    # Freeship: an all-or-nothing fee waiver, independent of discount_type/
    # discount_value above and independent of which (or how many)
    # categories the student is enrolled in. See app.services.fees --
    # compute_student_fee_breakdown()/compute_fee_breakdowns_bulk() short-
    # circuit to an empty, all-zero breakdown for a freeship student before
    # ever looking at their enrollments or the regular discount, so a
    # freeship student's fee is 0 the same way regardless of what they're
    # enrolled in or what discount they'd otherwise have.
    is_freeship: bool = Field(default=False)

    class_level: "ClassLevel" = Relationship(back_populates="students")
    enrollments: List["Enrollment"] = Relationship(back_populates="student")
    fee_cycles: List["FeeCycle"] = Relationship(back_populates="student")
    attendance_records: List["AttendanceRecord"] = Relationship(back_populates="student")
