"""One row per "record a payment" action from the fee cycles page — the
receipt data for the due-carry-forward flow (see
app.services.fee_payments.record_payment). Distinct from FeeCycle itself:
a single payment can settle several old cycles at once (FIFO, oldest
first) plus partially pay the newest one, so this is a snapshot of the
*transaction*, not of any one cycle.

anchor_cycle_id is the cycle the admin actually clicked "Pay" on (always
the most recent period in the payment's FIFO queue) — used to link back
to "which month was this payment made against" and to reopen the receipt
later. previous_due_amount/previous_due_months describe ONLY the cycles
strictly before the anchor period that were still outstanding at the
moment this payment was recorded — not a live, ever-changing number, so
an old receipt keeps showing exactly what it showed the day it was
issued even after later payments change the student's current balance.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlmodel import Field, SQLModel


class FeePayment(SQLModel, table=True):
    __tablename__ = "fee_payment"

    id: Optional[int] = Field(default=None, primary_key=True)
    student_id: int = Field(foreign_key="student.id", index=True)
    anchor_cycle_id: int = Field(foreign_key="fee_cycle.id", index=True)

    previous_due_amount: Decimal = Field(max_digits=10, decimal_places=2)
    previous_due_months: int
    current_month_due: Decimal = Field(max_digits=10, decimal_places=2)
    amount_paid: Decimal = Field(max_digits=10, decimal_places=2)
    remaining_due: Decimal = Field(max_digits=10, decimal_places=2)

    created_by_id: int = Field(foreign_key="admin_user.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
