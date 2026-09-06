"""Add FeeCategory.OTHERS

Revision ID: b91f4a7c3d56
Revises: a7d3e9c15f28
Create Date: 2026-09-25 00:00:00.000000

Fifth enrollment category, alongside School/Coaching/Language/Computer
Courses. Like Language and Computer, it isn't tied to class level -- one
flat "All classes" CategoryFeeDefault band (offset 0-14), seeded here at
the same Rs 1000/month placeholder every other category originally
started at (see scripts/seed_reference_data.py's DEFAULT_FEE) -- an admin
should set the real rate on /category-fees before enrolling anyone in it.

Postgres won't let a value just added via ALTER TYPE ... ADD VALUE be
used (e.g. in an INSERT) within the SAME transaction that added it. The
ADD VALUE runs inside op.get_context().autocommit_block() below, which
commits it immediately and outside Alembic's normal one-transaction-per-
migration wrapping, so the INSERT right after it (back in the normal
transactional block) can safely reference 'others' without a second
migration file just to bridge the two.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b91f4a7c3d56"
down_revision = "a7d3e9c15f28"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE feecategory ADD VALUE IF NOT EXISTS 'others'")

    op.execute(
        """
        INSERT INTO category_fee_default (category, band_name, min_class_offset, max_class_offset, default_amount)
        SELECT 'others', 'All classes', 0, 14, 1000.00
        WHERE NOT EXISTS (
            SELECT 1 FROM category_fee_default WHERE category = 'others' AND min_class_offset = 0
        )
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM category_fee_default WHERE category = 'others'")

    # Removing 'others' from a Postgres enum isn't a simple ALTER TYPE --
    # it requires rebuilding the type, and only works if NOTHING still
    # references the value being removed. Any Enrollment row with
    # category='others' must be reassigned or deleted before this can
    # run -- same caution as f4c7b28e91a3's FeeCycleStatus downgrade.
    op.execute("ALTER TYPE feecategory RENAME TO feecategory_old")
    _new_enum = postgresql.ENUM("school", "coaching", "english", "computer", name="feecategory")
    _new_enum.create(op.get_bind(), checkfirst=True)
    op.execute(
        "ALTER TABLE enrollment ALTER COLUMN category TYPE feecategory "
        "USING category::text::feecategory"
    )
    op.execute(
        "ALTER TABLE category_fee_default ALTER COLUMN category TYPE feecategory "
        "USING category::text::feecategory"
    )
    op.execute("DROP TYPE feecategory_old")
