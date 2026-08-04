"""add notification table

Revision ID: d92b5f7c1a34
Revises: c47a1e9d3b62
Create Date: 2026-08-04 15:30:00.000000

Phase 1 of the notification feature: a notification table, one row per
fee-payment event, for the super admin's notification bell (Phase 6).

student_name, fee_amount, and collected_by_name are snapshotted at
creation time (same rationale as fee_cycle.category_breakdown) so a later
student rename or admin-user change never rewrites what a past
notification said happened. student_id and collected_by_id are kept
alongside for linking back; collected_by_id is nullable since a paid
fee cycle can in principle have no resolvable admin identity.
"""
from alembic import op
import sqlalchemy as sa


revision = "d92b5f7c1a34"
down_revision = "c47a1e9d3b62"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("student_name", sa.String(length=150), nullable=False),
        sa.Column("fee_amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("collected_by_id", sa.Integer(), nullable=True),
        sa.Column("collected_by_name", sa.String(length=150), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["student_id"], ["student.id"]),
        sa.ForeignKeyConstraint(["collected_by_id"], ["admin_user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_notification_student_id"), "notification", ["student_id"], unique=False
    )
    op.create_index(
        op.f("ix_notification_created_at"), "notification", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_notification_is_read"), "notification", ["is_read"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_notification_is_read"), table_name="notification")
    op.drop_index(op.f("ix_notification_created_at"), table_name="notification")
    op.drop_index(op.f("ix_notification_student_id"), table_name="notification")
    op.drop_table("notification")
