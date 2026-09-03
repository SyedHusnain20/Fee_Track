"""Exam fee + due-carry-forward partial payments

Revision ID: f4c7b28e91a3
Revises: e5b8c14f2a97
Create Date: 2026-09-15 00:00:00.000000

Two independent features landing together since both touch FeeCycle:

1. Exam fee (School-only, per period): a new exam_fee_setting table
   records one amount per period. fee_cycle gains a matching exam_fee
   column so each cycle snapshots the amount actually charged to it
   (folded into total_due/subtotal at apply/generation time — see
   app.services.exam_fee), independent of whatever exam_fee_setting
   says today.

2. Due-carry-forward partial payments: fee_cycle gains amount_paid
   (0 by default, == total_due once fully PAID) and FeeCycleStatus
   gains a third value, 'partial', for a cycle that's collected some
   but not all of its total_due. Recording a payment (see
   app.services.fee_payments) can touch several old cycles in one go,
   so the receipt for a single payment transaction is its own table,
   fee_payment, rather than something that fits on any one FeeCycle row.

Existing fee_cycle rows: exam_fee defaults to 0.00 (none of them had an
exam fee applied, by construction — this feature didn't exist yet).
amount_paid backfills to total_due for every already-PAID row (they were,
by definition, paid in full under the old binary status) and to 0.00 for
every UNPAID row.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f4c7b28e91a3"
down_revision = "e5b8c14f2a97"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- FeeCycleStatus: add 'partial' -------------------------------
    # Postgres 12+ allows ADD VALUE inside a transaction as long as the
    # new value isn't also used within that same transaction — which it
    # isn't here (the data backfill below only ever sets 'paid' or
    # leaves 'unpaid' as-is).
    op.execute("ALTER TYPE feecyclestatus ADD VALUE IF NOT EXISTS 'partial'")

    # --- fee_cycle: exam_fee + amount_paid ----------------------------
    op.add_column(
        "fee_cycle",
        sa.Column("exam_fee", sa.Numeric(10, 2), nullable=False, server_default="0.00"),
    )
    op.add_column(
        "fee_cycle",
        sa.Column("amount_paid", sa.Numeric(10, 2), nullable=False, server_default="0.00"),
    )
    op.execute("UPDATE fee_cycle SET amount_paid = total_due WHERE status = 'paid'")
    # server_default only exists to backfill existing rows cleanly —
    # every future insert (fee_cycle_generation.py, fee_payments.py)
    # always sets both columns explicitly, matching this table's existing
    # snapshot-not-default philosophy for its other columns.
    op.alter_column("fee_cycle", "exam_fee", server_default=None)
    op.alter_column("fee_cycle", "amount_paid", server_default=None)

    # --- exam_fee_setting ----------------------------------------------
    op.create_table(
        "exam_fee_setting",
        sa.Column("period", sa.String(length=7), primary_key=True),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("admin_user.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("admin_user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    # --- fee_payment -----------------------------------------------------
    op.create_table(
        "fee_payment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("student.id"), nullable=False),
        sa.Column("anchor_cycle_id", sa.Integer(), sa.ForeignKey("fee_cycle.id"), nullable=False),
        sa.Column("previous_due_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("previous_due_months", sa.Integer(), nullable=False),
        sa.Column("current_month_due", sa.Numeric(10, 2), nullable=False),
        sa.Column("amount_paid", sa.Numeric(10, 2), nullable=False),
        sa.Column("remaining_due", sa.Numeric(10, 2), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("admin_user.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_fee_payment_student_id", "fee_payment", ["student_id"])
    op.create_index("ix_fee_payment_anchor_cycle_id", "fee_payment", ["anchor_cycle_id"])


def downgrade() -> None:
    op.drop_index("ix_fee_payment_anchor_cycle_id", table_name="fee_payment")
    op.drop_index("ix_fee_payment_student_id", table_name="fee_payment")
    op.drop_table("fee_payment")
    op.drop_table("exam_fee_setting")

    op.drop_column("fee_cycle", "amount_paid")
    op.drop_column("fee_cycle", "exam_fee")

    # Removing 'partial' from a Postgres enum isn't a simple ALTER TYPE —
    # it requires rebuilding the type. Any row still using 'partial' at
    # downgrade time must be resolved (moved to 'unpaid' or 'paid')
    # before this runs, matching the caution note on d4a8f21b6e57's
    # comparable AttendanceSession downgrade.
    op.execute("UPDATE fee_cycle SET status = 'unpaid' WHERE status = 'partial'")
    op.execute("ALTER TYPE feecyclestatus RENAME TO feecyclestatus_old")
    _new_enum = postgresql.ENUM("unpaid", "paid", name="feecyclestatus")
    _new_enum.create(op.get_bind(), checkfirst=True)
    op.execute(
        "ALTER TABLE fee_cycle ALTER COLUMN status TYPE feecyclestatus "
        "USING status::text::feecyclestatus"
    )
    op.execute("DROP TYPE feecyclestatus_old")
