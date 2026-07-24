from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column
from sqlmodel import Field, Relationship, SQLModel, UniqueConstraint

from app.models._enum_utils import str_enum_type
from app.models.enums import FeeCycleStatus

if TYPE_CHECKING:
    from app.models.student import Student


class FeeCycle(SQLModel, table=True):
    __tablename__ = "fee_cycle"
    __table_args__ = (UniqueConstraint("student_id", "period", name="uq_fee_cycle_student_period"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    student_id: int = Field(foreign_key="student.id", index=True)
    period: str = Field(max_length=7)  # "YYYY-MM"
    total_due: Decimal = Field(max_digits=10, decimal_places=2)  # snapshotted, immutable after
    status: FeeCycleStatus = Field(
        default=FeeCycleStatus.UNPAID,
        sa_column=Column(str_enum_type(FeeCycleStatus), nullable=False, index=True),
    )
    paid_date: Optional[date] = Field(default=None)

    created_by_id: int = Field(foreign_key="admin_user.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_by_id: Optional[int] = Field(default=None, foreign_key="admin_user.id")
    updated_at: Optional[datetime] = Field(default=None)

    student: "Student" = Relationship(back_populates="fee_cycles")
