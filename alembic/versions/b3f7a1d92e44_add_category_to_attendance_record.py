"""add category to attendance_record + one-scan-per-category-per-day

Revision ID: b3f7a1d92e44
Revises: 8f3d1a9b6c22
Create Date: 2026-07-17 00:00:00.000000

Adds the category column Step 9's kiosk needs. AttendanceRecord originally
had no way to record which category a scan was for, which meant "already
scanned today" couldn't be told apart from "already scanned for Coaching
today" — a student legitimately attending both School and Coaching the
same day looked identical to a duplicate scan.

Safe to add as NOT NULL with no default: attendance_record has been empty
since Step 5 — nothing wrote to it before this kiosk build. If you've
inserted manual test rows into that table since, truncate it first or this
migration will fail on the NOT NULL constraint.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b3f7a1d92e44"
down_revision = "8f3d1a9b6c22"
branch_labels = None
depends_on = None

_fee_category_enum = postgresql.ENUM(
    "school", "coaching", "english", "computer",
    name="feecategory", create_type=False,
)


def upgrade() -> None:
    op.add_column(
        "attendance_record",
        sa.Column("category", _fee_category_enum, nullable=False),
    )
    op.create_foreign_key(
        "fk_attendance_record_category_category_fee_default",
        "attendance_record", "category_fee_default",
        ["category"], ["category"],
    )
    op.create_index(
        "ix_attendance_record_category", "attendance_record", ["category"]
    )
    op.create_index(
        "ix_attendance_one_scan_per_student_category_day",
        "attendance_record", ["student_id", "scan_date", "category"],
        unique=True, postgresql_where=sa.text("student_id IS NOT NULL"),
    )
    op.create_index(
        "ix_attendance_one_scan_per_teacher_category_day",
        "attendance_record", ["teacher_id", "scan_date", "category"],
        unique=True, postgresql_where=sa.text("teacher_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_attendance_one_scan_per_teacher_category_day", table_name="attendance_record")
    op.drop_index("ix_attendance_one_scan_per_student_category_day", table_name="attendance_record")
    op.drop_index("ix_attendance_record_category", table_name="attendance_record")
    op.drop_constraint(
        "fk_attendance_record_category_category_fee_default",
        "attendance_record", type_="foreignkey",
    )
    op.drop_column("attendance_record", "category")