"""One row per period ("YYYY-MM") recording the exam fee amount applied
to School students for that month — see app.services.exam_fee.

Applying an exam fee for a period is idempotent-by-replacement: applying
again for the same period overwrites the amount (not additive), and
re-applies it to every School-enrolled student's cycle for that period,
whether that cycle already existed or gets generated afterward. A period
with no row here has no exam fee — the default, and the state every
period is in until an admin explicitly applies one.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlmodel import Field, SQLModel


class ExamFeeSetting(SQLModel, table=True):
    __tablename__ = "exam_fee_setting"

    period: str = Field(primary_key=True, max_length=7)  # "YYYY-MM"
    amount: Decimal = Field(max_digits=10, decimal_places=2)

    created_by_id: int = Field(foreign_key="admin_user.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_by_id: Optional[int] = Field(default=None, foreign_key="admin_user.id")
    updated_at: Optional[datetime] = Field(default=None)
