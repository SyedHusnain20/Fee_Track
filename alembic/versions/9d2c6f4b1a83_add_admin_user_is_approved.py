"""add is_approved to admin_user

Revision ID: 9d2c6f4b1a83
Revises: 2b21836b5b6b
Create Date: 2026-08-01 15:28:54.770231

Phase 1 of the admin self-signup + super-admin approval feature.

Adds admin_user.is_approved (NOT NULL, default True). True is the correct
default for this migration's backfill: every AdminUser row that exists
today was created directly by a super admin via admin_accounts.py, which
never went through an approval step, so treating existing accounts as
already-approved preserves their ability to log in.

Server default is intentionally left in place after the backfill (rather
than dropped, as some other migrations in this history do for backfilled
columns) because admin_accounts.create_admin — the super-admin-driven
creation path — should also continue to produce approved accounts without
every call site needing to pass is_approved explicitly. Only the new
public /signup route (Phase 2) will override it to False.

Rejection in this feature is modeled as a hard delete of the AdminUser row
(per product decision), not a third status value, so no enum/status column
is introduced here — a plain boolean is sufficient.
"""
from alembic import op
import sqlalchemy as sa


revision = "9d2c6f4b1a83"
down_revision = "2b21836b5b6b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "admin_user",
        sa.Column(
            "is_approved",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("admin_user", "is_approved")