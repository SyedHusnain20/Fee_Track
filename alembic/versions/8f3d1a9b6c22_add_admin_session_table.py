"""add admin_session table for step 6 auth

Revision ID: 8f3d1a9b6c22
Revises: 1c04d250a5d7
Create Date: 2026-07-12 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision = "8f3d1a9b6c22"
down_revision = "1c04d250a5d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_session",
        sa.Column("token", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("admin_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("user_agent", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.ForeignKeyConstraint(["admin_id"], ["admin_user.id"], ),
        sa.PrimaryKeyConstraint("token"),
    )
    op.create_index(op.f("ix_admin_session_admin_id"), "admin_session", ["admin_id"], unique=False)
    op.create_index(op.f("ix_admin_session_expires_at"), "admin_session", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_admin_session_expires_at"), table_name="admin_session")
    op.drop_index(op.f("ix_admin_session_admin_id"), table_name="admin_session")
    op.drop_table("admin_session")
