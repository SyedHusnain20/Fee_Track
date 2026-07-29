"""add itemized breakdown snapshot + collected_by to fee_cycle

Revision ID: c58e0d3a9f16
Revises: a3f9c81b2d47
Create Date: 2026-07-30 00:00:00.000000

Powers the itemized invoice: per-category breakdown, subtotal, discount
(type/value/amount), and who actually collected the payment. All
snapshotted at generation time, same immutability guarantee as total_due
already had — a later change to category band rates or a student's
discount must never retroactively rewrite what a past invoice says.

Reuses the existing `discounttype` Postgres enum (see
a3f9c81b2d47_move_discount_to_student.py) for fee_cycle.discount_type.

Data migration for EXISTING rows: there's no way to reconstruct the
per-category breakdown or the discount that was actually in effect when
an old cycle was generated -- that data was simply never captured before
this migration. Existing rows get:
  - subtotal = total_due (best available guess: assumes no discount was
    in effect, since none was ever tracked)
  - discount_type = 'none', discount_value = NULL, discount_amount = 0.00
  - category_breakdown = NULL (the invoice template shows a "breakdown
    not available for this older invoice" fallback rather than a wrong
    per-category split)
  - collected_by_id = NULL (unknown who actually collected historically;
    the audit_log's who-changed-status-when history still exists
    separately, this is only the newer explicit "collected by" pointer)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c58e0d3a9f16"
down_revision = "a3f9c81b2d47"
branch_labels = None
depends_on = None

_discount_type_enum = postgresql.ENUM(
    "none", "fixed", "percentage",
    name="discounttype", create_type=False,
)


def upgrade() -> None:
    op.add_column(
        "fee_cycle",
        sa.Column("category_breakdown", postgresql.JSON(astext_type=sa.Text()), nullable=True),
    )

    op.add_column("fee_cycle", sa.Column("subtotal", sa.Numeric(10, 2), nullable=True))
    op.execute("UPDATE fee_cycle SET subtotal = total_due")
    op.alter_column("fee_cycle", "subtotal", nullable=False)

    op.add_column(
        "fee_cycle",
        sa.Column(
            "discount_type", _discount_type_enum,
            nullable=False, server_default="none",
        ),
    )
    op.alter_column("fee_cycle", "discount_type", server_default=None)

    op.add_column("fee_cycle", sa.Column("discount_value", sa.Numeric(10, 2), nullable=True))

    op.add_column(
        "fee_cycle",
        sa.Column("discount_amount", sa.Numeric(10, 2), nullable=False, server_default="0.00"),
    )
    op.alter_column("fee_cycle", "discount_amount", server_default=None)

    op.add_column(
        "fee_cycle",
        sa.Column("collected_by_id", sa.Integer(), sa.ForeignKey("admin_user.id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("fee_cycle", "collected_by_id")
    op.drop_column("fee_cycle", "discount_amount")
    op.drop_column("fee_cycle", "discount_value")
    op.drop_column("fee_cycle", "discount_type")
    op.drop_column("fee_cycle", "subtotal")
    op.drop_column("fee_cycle", "category_breakdown")
