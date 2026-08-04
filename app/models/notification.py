from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlmodel import Field, SQLModel


class Notification(SQLModel, table=True):
    """One row per fee-payment event, surfaced to the super admin via the
    notification bell (Phase 6). There's no scheduler/cron in this app, so
    old read notifications are pruned opportunistically — see
    app/services/notifications.py — rather than on a timer.

    student_name, fee_amount, and collected_by_name are snapshotted at
    creation time, same rationale as FeeCycle's category_breakdown/
    total_due: a later student rename or admin-user change must never
    rewrite what a past notification said happened. student_id and
    collected_by_id are kept alongside for linking back (e.g. "view
    student"), but the display fields never re-derive from them.

    No ORM Relationship() to Student/AdminUser, matching the rest of this
    codebase's FK convention (see FeeCycle.collected_by_id, Holiday.marked_by_id).
    """

    __tablename__ = "notification"

    id: Optional[int] = Field(default=None, primary_key=True)

    student_id: int = Field(foreign_key="student.id", index=True)
    student_name: str = Field(max_length=150)

    fee_amount: Decimal = Field(max_digits=10, decimal_places=2)

    # Nullable: a fee cycle can in principle be marked paid without a
    # resolvable admin identity (defensive, mirrors FeeCycle.collected_by_id
    # being Optional). collected_by_name is the display fallback if the
    # admin user is later deleted.
    collected_by_id: Optional[int] = Field(default=None, foreign_key="admin_user.id")
    collected_by_name: str = Field(max_length=150)

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    is_read: bool = Field(default=False, index=True)
