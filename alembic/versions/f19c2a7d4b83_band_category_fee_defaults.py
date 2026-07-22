"""restructure category_fee_default into class-level fee bands

Revision ID: f19c2a7d4b83
Revises: d4a8f21b6e57
Create Date: 2026-07-21 00:00:00.000000

Restructures CategoryFeeDefault from "one flat fee per category" (4 rows,
category as primary key) into "one fee per (category, class-level band)"
(11 rows total: School=4 bands, Coaching=5 bands, English=1 flat band,
Computer=1 flat band). Bands are expressed as class_offset ranges (see
class_level.py: Foundation 1-3 -> offsets 0-2, Class 1-12 -> offsets 3-14):

  School:    F1-3 (0-2), Class 1-5 (3-7), Class 6-8 (8-10), Class 9-10 (11-12)
  Coaching:  same 4 bands as School, PLUS Class 11-12 (13-14)
  English:   flat, one band covering the full range (0-14)
  Computer:  flat, one band covering the full range (0-14)

This is also what makes Class 9-10 the effective ceiling for School
enrollment: nothing enforces that as a separately hardcoded rule --
app/services/fees.py's band lookup simply has no match above offset 12
for category='school', and app/api/enrollments.py's create_enrollment now
requires a matching band to exist before allowing an enrollment at all.
If the band boundaries ever change, the enrollment ceiling moves with
them automatically, from this single source of truth.

Drops the FK from enrollment.category -> category_fee_default.category:
category_fee_default.category is no longer unique (multiple band rows
per category now), so it can't be an FK target anymore. FeeCategory stays
validated at the Postgres ENUM-type level -- the same mechanism already
used elsewhere in this codebase (attendance_record.session has never had
an FK to any table).

Data migration: each category's existing flat default_amount is copied
into EVERY new band for that category as a starting placeholder -- e.g.
if Coaching's old flat default was Rs 2000, all 5 new Coaching bands
start at Rs 2000 each. These are NOT real per-band prices; review and
correct each one on /category-fees before relying on them for real
billing -- same "seed placeholder, admin corrects" pattern used for
attendance timing settings in Step 9.

PRE-FLIGHT: confirm the actual FK constraint name before running --
    SELECT conname FROM pg_constraint WHERE conrelid = 'enrollment'::regclass AND contype = 'f';
This migration assumes Postgres's standard auto-generated name
(enrollment_category_fkey). If that query returns something different,
update the constraint name below before running.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f19c2a7d4b83"
down_revision = "d4a8f21b6e57"
branch_labels = None
depends_on = None

_fee_category_enum = postgresql.ENUM(
    "school", "coaching", "english", "computer",
    name="feecategory", create_type=False,
)

# (category, band_name, min_class_offset, max_class_offset)
_BANDS = [
    ("school", "Foundation 1-3", 0, 2),
    ("school", "Class 1-5", 3, 7),
    ("school", "Class 6-8", 8, 10),
    ("school", "Class 9-10", 11, 12),
    ("coaching", "Foundation 1-3", 0, 2),
    ("coaching", "Class 1-5", 3, 7),
    ("coaching", "Class 6-8", 8, 10),
    ("coaching", "Class 9-10", 11, 12),
    ("coaching", "Class 11-12", 13, 14),
    ("english", "All classes", 0, 14),
    ("computer", "All classes", 0, 14),
]


def upgrade() -> None:
    bind = op.get_bind()

    # Capture the old flat defaults BEFORE restructuring the table.
    old_defaults = dict(
        bind.execute(sa.text("SELECT category, default_amount FROM category_fee_default")).fetchall()
    )

    op.drop_constraint("enrollment_category_fkey", "enrollment", type_="foreignkey")
    op.drop_table("category_fee_default")

    op.create_table(
        "category_fee_default",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("category", _fee_category_enum, nullable=False),
        sa.Column("band_name", sa.String(length=50), nullable=False),
        sa.Column("min_class_offset", sa.Integer(), nullable=False),
        sa.Column("max_class_offset", sa.Integer(), nullable=False),
        sa.Column("default_amount", sa.Numeric(10, 2), nullable=False),
        sa.CheckConstraint("min_class_offset <= max_class_offset", name="ck_category_fee_band_range"),
    )
    op.create_index("ix_category_fee_default_category", "category_fee_default", ["category"])
    op.create_index(
        "ix_category_fee_default_category_band",
        "category_fee_default", ["category", "min_class_offset"],
        unique=True,
    )

    fee_table = sa.table(
        "category_fee_default",
        sa.column("category"), sa.column("band_name"),
        sa.column("min_class_offset"), sa.column("max_class_offset"),
        sa.column("default_amount"),
    )
    for category, band_name, min_offset, max_offset in _BANDS:
        placeholder_amount = old_defaults.get(category, 0)
        op.bulk_insert(fee_table, [{
            "category": category, "band_name": band_name,
            "min_class_offset": min_offset, "max_class_offset": max_offset,
            "default_amount": placeholder_amount,
        }])


def downgrade() -> None:
    bind = op.get_bind()

    # LOSSY: collapses each category's multiple bands back to one flat
    # value via averaging. Real per-band pricing entered after upgrade is
    # not recoverable exactly.
    rows = bind.execute(
        sa.text("SELECT category, AVG(default_amount) AS avg_amount FROM category_fee_default GROUP BY category")
    ).fetchall()
    averaged = {category: amount for category, amount in rows}

    op.drop_index("ix_category_fee_default_category_band", table_name="category_fee_default")
    op.drop_index("ix_category_fee_default_category", table_name="category_fee_default")
    op.drop_table("category_fee_default")

    op.create_table(
        "category_fee_default",
        sa.Column("category", _fee_category_enum, primary_key=True),
        sa.Column("default_amount", sa.Numeric(10, 2), nullable=False),
    )
    fee_table = sa.table("category_fee_default", sa.column("category"), sa.column("default_amount"))
    for category, amount in averaged.items():
        op.bulk_insert(fee_table, [{"category": category, "default_amount": amount}])

    op.create_foreign_key(
        "enrollment_category_fkey", "enrollment", "category_fee_default",
        ["category"], ["category"],
    )