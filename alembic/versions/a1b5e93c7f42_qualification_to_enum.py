"""convert teacher.qualification to fixed enum

Revision ID: a1b5e93c7f42
Revises: e7a2b4c9d158
Create Date: 2026-08-01 00:00:00.000000

Phase 1 follow-up: the teacher form's qualification field becomes a fixed
dropdown (Intermediate / Graduate / Masters / PhD) instead of free text, so
the DB column changes from VARCHAR(150) to a native Postgres enum matching
app.models.enums.Qualification (values: intermediate, graduate, masters,
phd), same pattern as the other str_enum_type columns in this codebase.

No teacher rows existed with free-text qualification data at the time this
migration was written (the field was only added in e7a2b4c9d158, the
previous migration, with no seed data ever populating it) -- but the
upgrade is still written defensively: any existing value that doesn't
case-insensitively match one of the four allowed labels is nulled out
rather than left dangling or causing the type cast to fail, since a
free-text value like "M.Sc. Mathematics" has no safe automatic mapping
onto the fixed list. Affected teachers show a blank qualification after
this migration and can be corrected once via the edit form.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a1b5e93c7f42"
down_revision = "e7a2b4c9d158"
branch_labels = None
depends_on = None

_qualification_enum = postgresql.ENUM(
    "intermediate", "graduate", "masters", "phd", name="qualification", create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    _qualification_enum.create(bind, checkfirst=True)

    # Null out anything that isn't an exact (case-insensitive) match for
    # one of the four allowed values, so the type cast below can't fail.
    op.execute(
        "UPDATE teacher SET qualification = NULL "
        "WHERE qualification IS NOT NULL "
        "AND lower(qualification) NOT IN ('intermediate', 'graduate', 'masters', 'phd')"
    )
    op.execute(
        "UPDATE teacher SET qualification = lower(qualification) WHERE qualification IS NOT NULL"
    )

    op.alter_column(
        "teacher",
        "qualification",
        existing_type=sa.String(length=150),
        type_=_qualification_enum,
        postgresql_using="qualification::qualification",
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "teacher",
        "qualification",
        existing_type=_qualification_enum,
        type_=sa.String(length=150),
        postgresql_using="qualification::text",
        nullable=True,
    )
    _qualification_enum.drop(op.get_bind(), checkfirst=True)
