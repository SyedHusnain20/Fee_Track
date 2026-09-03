"""Add student.is_freeship

Revision ID: a7d3e9c15f28
Revises: f4c7b28e91a3
Create Date: 2026-09-20 00:00:00.000000

Freeship: an all-or-nothing fee waiver set at student-add (or edit) time,
independent of discount_type/discount_value and independent of which
categories the student is enrolled in. See app.services.fees for how this
short-circuits fee computation to zero.

Existing rows default to false -- nobody currently in the system was
marked freeship before this feature existed.
"""
from alembic import op
import sqlalchemy as sa

revision = "a7d3e9c15f28"
down_revision = "f4c7b28e91a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "student",
        sa.Column("is_freeship", sa.Boolean(), nullable=False, server_default="false"),
    )
    # server_default only exists to backfill existing rows -- every future
    # insert/update sets this explicitly (app/api/students.py), matching
    # this table's existing snapshot-not-default philosophy elsewhere.
    op.alter_column("student", "is_freeship", server_default=None)


def downgrade() -> None:
    op.drop_column("student", "is_freeship")
