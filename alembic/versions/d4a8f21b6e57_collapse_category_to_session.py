"""collapse attendance_record category to session (School/Academy)

Revision ID: d4a8f21b6e57
Revises: b3f7a1d92e44
Create Date: 2026-07-19 00:00:00.000000

Redesigns the kiosk-side category concept: FeeCategory (school/coaching/
english/computer) still drives billing unchanged, but attendance now
tracks against a new, separate 2-value AttendanceSession enum (school/
academy). A student enrolled in multiple Academy subcategories (Coaching +
English) gets ONE academy scan per day, not one per subcategory — this
falls directly out of collapsing the unique-per-category index down to
unique-per-session.

Data migration for existing rows:
  - category='school'                             -> session='school'
  - category IN ('coaching','english','computer')  -> session='academy'
  - punctuality_status is left AS-IS on historical rows.

CAUTION: if any student/teacher had 2+ same-day scans across Coaching/
English/Computer BEFORE this redesign, they collapse onto the same
(person, scan_date, 'academy') key and the new unique index rejects the
second one. Run this BEFORE upgrading:

    SELECT student_id, scan_date, COUNT(*)
    FROM attendance_record
    WHERE category IN ('coaching', 'english', 'computer')
    GROUP BY student_id, scan_date
    HAVING COUNT(*) > 1;
    -- repeat with teacher_id for teacher rows
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d4a8f21b6e57"
down_revision = "b3f7a1d92e44"
branch_labels = None
depends_on = None

_attendance_session_enum = postgresql.ENUM(
    "school", "academy", name="attendancesession", create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    _attendance_session_enum.create(bind, checkfirst=True)

    op.drop_index("ix_attendance_one_scan_per_teacher_category_day", table_name="attendance_record")
    op.drop_index("ix_attendance_one_scan_per_student_category_day", table_name="attendance_record")
    op.drop_constraint(
        "fk_attendance_record_category_category_fee_default",
        "attendance_record", type_="foreignkey",
    )
    op.drop_index("ix_attendance_record_category", table_name="attendance_record")

    op.add_column(
        "attendance_record",
        sa.Column("session", _attendance_session_enum, nullable=True),
    )
    op.execute("UPDATE attendance_record SET session = 'school' WHERE category = 'school'")
    op.execute(
        "UPDATE attendance_record SET session = 'academy' "
        "WHERE category IN ('coaching', 'english', 'computer')"
    )
    op.alter_column("attendance_record", "session", nullable=False)

    op.drop_column("attendance_record", "category")

    op.create_index("ix_attendance_record_session", "attendance_record", ["session"])
    op.create_index(
        "ix_attendance_one_scan_per_student_session_day",
        "attendance_record", ["student_id", "scan_date", "session"],
        unique=True, postgresql_where=sa.text("student_id IS NOT NULL"),
    )
    op.create_index(
        "ix_attendance_one_scan_per_teacher_session_day",
        "attendance_record", ["teacher_id", "scan_date", "session"],
        unique=True, postgresql_where=sa.text("teacher_id IS NOT NULL"),
    )

    op.alter_column("attendance_record", "punctuality_status", nullable=True)

    op.execute(
        "DELETE FROM system_setting WHERE key IN ("
        "'coaching_start_time', 'coaching_grace_minutes', "
        "'english_start_time', 'english_grace_minutes', "
        "'computer_start_time', 'computer_grace_minutes'"
        ")"
    )


def downgrade() -> None:
    _fee_category_enum = postgresql.ENUM(
        "school", "coaching", "english", "computer",
        name="feecategory", create_type=False,
    )

    op.drop_index("ix_attendance_one_scan_per_teacher_session_day", table_name="attendance_record")
    op.drop_index("ix_attendance_one_scan_per_student_session_day", table_name="attendance_record")
    op.drop_index("ix_attendance_record_session", table_name="attendance_record")

    op.add_column(
        "attendance_record",
        sa.Column("category", _fee_category_enum, nullable=True),
    )
    op.execute("UPDATE attendance_record SET category = 'school' WHERE session = 'school'")
    op.execute("UPDATE attendance_record SET category = 'coaching' WHERE session = 'academy'")
    op.alter_column("attendance_record", "category", nullable=False)

    op.drop_column("attendance_record", "session")

    op.create_foreign_key(
        "fk_attendance_record_category_category_fee_default",
        "attendance_record", "category_fee_default",
        ["category"], ["category"],
    )
    op.create_index("ix_attendance_record_category", "attendance_record", ["category"])
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

    op.alter_column("attendance_record", "punctuality_status", nullable=False)

    _attendance_session_enum.drop(op.get_bind(), checkfirst=True)