"""add teacher date_joined

Revision ID: b6d1f84a2c93
Revises: a1b5e93c7f42
Create Date: 2026-08-01 00:00:00.000000

Fixes a real gap in the Phase 3 salary calculation: without a join date,
app.services.teacher_salary had no way to tell a teacher hired mid-month
apart from one who was simply absent before they joined, so it counted
every working day from the 1st of the month regardless of when someone
actually started -- wrongly showing a brand-new hire as absent for days
before their employment began.

Nullable in the DB for the same backward-compatibility reason as the rest
of the Phase 1 teacher fields (existing rows have no join date on record).
For a teacher with no date_joined set, app.services.teacher_salary falls
back to its old behavior (counts from the 1st) -- only new/edited
teachers going forward, where the form now requires this field, get the
corrected mid-month clipping.
"""
from alembic import op
import sqlalchemy as sa

revision = "b6d1f84a2c93"
down_revision = "a1b5e93c7f42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("teacher", sa.Column("date_joined", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("teacher", "date_joined")
