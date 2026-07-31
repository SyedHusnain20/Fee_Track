"""add teacher profile fields

Revision ID: e7a2b4c9d158
Revises: c58e0d3a9f16
Create Date: 2026-07-31 00:00:00.000000

Phase 1 of the Teacher-expansion work: adds father_name, contact,
qualification, designation, salary, and four subjects-taught booleans
(teaches_school/teaches_coaching/teaches_english/teaches_computer) to the
teacher table.

All new columns are added nullable (booleans with server_default 'false')
so this is safe against existing teacher rows created before this
migration, which have none of this data. The create/edit form
(app/api/teachers.py) requires all of them going forward for new
submissions, but the DB itself doesn't enforce that -- same "nullable in
DB, required in form" split already used elsewhere in this codebase
(e.g. FeeCycle.category_breakdown being None for pre-existing rows).
"""
from alembic import op
import sqlalchemy as sa

revision = "e7a2b4c9d158"
down_revision = "c58e0d3a9f16"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("teacher", sa.Column("father_name", sa.String(length=150), nullable=True))
    op.add_column("teacher", sa.Column("contact", sa.String(length=20), nullable=True))
    op.add_column("teacher", sa.Column("qualification", sa.String(length=150), nullable=True))
    op.add_column("teacher", sa.Column("designation", sa.String(length=100), nullable=True))
    op.add_column(
        "teacher",
        sa.Column("salary", sa.Numeric(precision=10, scale=2), nullable=True),
    )
    op.add_column(
        "teacher",
        sa.Column(
            "teaches_school", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "teacher",
        sa.Column(
            "teaches_coaching", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "teacher",
        sa.Column(
            "teaches_english", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "teacher",
        sa.Column(
            "teaches_computer", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    op.drop_column("teacher", "teaches_computer")
    op.drop_column("teacher", "teaches_english")
    op.drop_column("teacher", "teaches_coaching")
    op.drop_column("teacher", "teaches_school")
    op.drop_column("teacher", "salary")
    op.drop_column("teacher", "designation")
    op.drop_column("teacher", "qualification")
    op.drop_column("teacher", "contact")
    op.drop_column("teacher", "father_name")
