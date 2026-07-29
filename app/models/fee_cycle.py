from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, Relationship, SQLModel, UniqueConstraint

from app.models._enum_utils import str_enum_type
from app.models.enums import DiscountType, FeeCycleStatus

if TYPE_CHECKING:
    from app.models.student import Student


class FeeCycle(SQLModel, table=True):
    __tablename__ = "fee_cycle"
    __table_args__ = (UniqueConstraint("student_id", "period", name="uq_fee_cycle_student_period"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    student_id: int = Field(foreign_key="student.id", index=True)
    period: str = Field(max_length=7)  # "YYYY-MM"
    total_due: Decimal = Field(max_digits=10, decimal_places=2)  # snapshotted, immutable after

    # Everything below is ALSO snapshotted at generation time, same as
    # total_due — a later change to the student's discount or the category
    # band rates must never retroactively rewrite what a past invoice
    # says. subtotal - discount_amount == total_due, always. Powers the
    # itemized invoice (category breakdown + discount line). See
    # app/services/fee_cycle_generation.py.
    #
    # category_breakdown is {FeeCategory.value: "amount"} — a plain dict,
    # same JSON-snapshot pattern already used by AuditLog.before_value/
    # after_value, rather than a child table: this data is always read as
    # a whole alongside its cycle, never queried per-category across
    # cycles, and the category set is small and fixed (4 values).
    # None for any cycle generated before this field existed (see the
    # migration that added it) — the invoice falls back to just showing
    # the total for those older cycles.
    category_breakdown: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    subtotal: Decimal = Field(default=Decimal("0.00"), max_digits=10, decimal_places=2)
    discount_type: DiscountType = Field(
        default=DiscountType.NONE,
        sa_column=Column(str_enum_type(DiscountType), nullable=False),
    )
    discount_value: Optional[Decimal] = Field(default=None, max_digits=10, decimal_places=2)
    discount_amount: Decimal = Field(default=Decimal("0.00"), max_digits=10, decimal_places=2)

    status: FeeCycleStatus = Field(
        default=FeeCycleStatus.UNPAID,
        sa_column=Column(str_enum_type(FeeCycleStatus), nullable=False, index=True),
    )
    paid_date: Optional[date] = Field(default=None)
    # Who actually marked this cycle paid, for the invoice's "Collected by"
    # line. Set on mark-paid, cleared back to None on mark-unpaid: a cycle
    # that isn't currently paid was never "collected" by anyone in the
    # present tense, regardless of who touched it historically (the audit
    # log already has that full history if it's ever needed). No ORM
    # Relationship() here, matching created_by_id/updated_by_id below —
    # this codebase looks these up manually where the admin's name is
    # actually needed rather than eager-loading a relationship for every
    # FeeCycle query.
    collected_by_id: Optional[int] = Field(default=None, foreign_key="admin_user.id")

    created_by_id: int = Field(foreign_key="admin_user.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_by_id: Optional[int] = Field(default=None, foreign_key="admin_user.id")
    updated_at: Optional[datetime] = Field(default=None)

    student: "Student" = Relationship(back_populates="fee_cycles")
