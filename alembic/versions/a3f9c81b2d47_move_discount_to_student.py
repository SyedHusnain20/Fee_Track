"""move discount from enrollment to student (single overall discount)

Revision ID: a3f9c81b2d47
Revises: f19c2a7d4b83
Create Date: 2026-07-29 00:00:00.000000

Discount used to live on Enrollment (discount_type/discount_value), so a
student enrolled in multiple categories (School, Coaching, English,
Computer) could end up with a different discount per category. Per
explicit decision, a student now gets exactly ONE overall discount,
applied once to their combined total across all active enrollments — see
app/models/student.py and app/services/fees.py.

Reuses the existing Postgres enum type `discounttype` (created by
1c04d250a5d7_add_core_models.py for enrollment.discount_type) rather than
creating a new one — same three values (none/fixed/percentage), just a
different table now.

NOT a data migration: existing enrollment.discount_type/discount_value
values are dropped, not copied to Student. A student who had different
discounts on different enrollments has no single unambiguous "correct"
value to migrate to automatically, and picking one silently (e.g. the
largest, or the first found) risks quietly changing what a real family
gets billed. Every student's new Student.discount_type starts at 'none' —
review and re-apply the correct overall discount per student manually
after this migration, via the student edit form, before relying on it for
real billing. Same "seed placeholder, admin corrects" pattern already used
for attendance timing (Step 9) and the category fee bands
(f19c2a7d4b83) — flagged explicitly here since this one has a direct
billing impact if skipped.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a3f9c81b2d47"
down_revision = "f19c2a7d4b83"
branch_labels = None
depends_on = None

_discount_type_enum = postgresql.ENUM(
    "none", "fixed", "percentage",
    name="discounttype", create_type=False,
)


def upgrade() -> None:
    op.add_column(
        "student",
        sa.Column(
            "discount_type", _discount_type_enum,
            nullable=False, server_default="none",
        ),
    )
    op.add_column(
        "student",
        sa.Column("discount_value", sa.Numeric(precision=10, scale=2), nullable=True),
    )
    # server_default was only needed to backfill existing rows without a
    # NOT NULL violation; the app always sends an explicit value going
    # forward (Student.discount_type's Python-side default), so drop it
    # to match how every other enum column in this codebase is defined.
    op.alter_column("student", "discount_type", server_default=None)

    op.drop_column("enrollment", "discount_type")
    op.drop_column("enrollment", "discount_value")


def downgrade() -> None:
    op.add_column(
        "enrollment",
        sa.Column(
            "discount_type", _discount_type_enum,
            nullable=False, server_default="none",
        ),
    )
    op.add_column(
        "enrollment",
        sa.Column("discount_value", sa.Numeric(precision=10, scale=2), nullable=True),
    )
    op.alter_column("enrollment", "discount_type", server_default=None)

    # LOSSY: whatever discount was set on Student is simply discarded here,
    # not redistributed back to that student's individual enrollments —
    # there's no unambiguous way to split one overall discount back into
    # several per-category ones.
    op.drop_column("student", "discount_type")
    op.drop_column("student", "discount_value")
