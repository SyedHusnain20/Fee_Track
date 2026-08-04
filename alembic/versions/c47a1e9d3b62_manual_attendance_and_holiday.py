"""manual attendance fields + holiday table

Revision ID: c47a1e9d3b62
Revises: 9d2c6f4b1a83
Create Date: 2026-08-04 09:00:00.000000

Phase 1 of two features:

1. Manual attendance entry: adds attendance_record.is_manual (NOT NULL,
   default false — every existing row is a real kiosk scan) and
   attendance_record.marked_by_id (nullable FK -> admin_user.id, since
   only a manual entry has an admin identity behind it; a kiosk scan has
   none, by design).

2. Holidays: new holiday table, one row per date the school is closed
   beyond the standing Sunday-off rule. holiday_date is unique so marking
   the same day twice can never create a duplicate row.
"""
from alembic import op
import sqlalchemy as sa


revision = "c47a1e9d3b62"
down_revision = "9d2c6f4b1a83"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "attendance_record",
        sa.Column(
            "is_manual",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "attendance_record",
        sa.Column("marked_by_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        op.f("ix_attendance_record_marked_by_id"),
        "attendance_record",
        ["marked_by_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_attendance_record_marked_by_id_admin_user",
        "attendance_record",
        "admin_user",
        ["marked_by_id"],
        ["id"],
    )

    op.create_table(
        "holiday",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("holiday_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("marked_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["marked_by_id"], ["admin_user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_holiday_holiday_date"), "holiday", ["holiday_date"], unique=True
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_holiday_holiday_date"), table_name="holiday")
    op.drop_table("holiday")

    op.drop_constraint(
        "fk_attendance_record_marked_by_id_admin_user",
        "attendance_record",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_attendance_record_marked_by_id"), table_name="attendance_record"
    )
    op.drop_column("attendance_record", "marked_by_id")
    op.drop_column("attendance_record", "is_manual")