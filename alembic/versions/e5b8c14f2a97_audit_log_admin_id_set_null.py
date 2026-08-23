"""audit_log.admin_id nullable + ON DELETE SET NULL

Revision ID: e5b8c14f2a97
Revises: d92b5f7c1a34
Create Date: 2026-08-19 00:00:00.000000

Fixes a bug where rejecting a pending admin request (admin_accounts.
reject_admin) always 500'd. Every self-signed-up AdminUser has an
AuditLog CREATE row that self-references it as the actor (no logged-in
admin exists yet at signup time to be the actor instead — see
auth.signup_submit). reject_admin hard-deletes that AdminUser row, but
audit_log.admin_id was a plain NOT NULL FK with Postgres's default
RESTRICT behavior, so the delete was always blocked by that very row.

Switching to ON DELETE SET NULL lets the AdminUser be removed while the
audit row survives (with admin_id now NULL) — before_value/after_value
already snapshot the actor's name/email at write time, so no forensic
detail is lost, only the live FK link to a row that no longer exists.

Constraint name (audit_log_admin_id_fkey) is Postgres's own default for
a single-column FK created with no explicit name, which is how it was
originally declared in 1c04d250a5d7_add_core_models.py's create_table.
"""
from alembic import op
import sqlalchemy as sa


revision = "e5b8c14f2a97"
down_revision = "d92b5f7c1a34"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("audit_log", "admin_id", nullable=True)
    op.drop_constraint("audit_log_admin_id_fkey", "audit_log", type_="foreignkey")
    op.create_foreign_key(
        "audit_log_admin_id_fkey",
        "audit_log",
        "admin_user",
        ["admin_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # LOSSY if any admin_id is currently NULL (i.e. its actor was
    # hard-deleted via reject_admin since this migration ran): those rows
    # have no admin to restore a value to, so downgrading a NOT NULL
    # constraint back on would fail outright. Rather than guess a
    # placeholder admin_id, this is left to be handled manually if ever
    # needed — same "don't silently invent data" stance as
    # a3f9c81b2d47_move_discount_to_student.py.
    op.drop_constraint("audit_log_admin_id_fkey", "audit_log", type_="foreignkey")
    op.create_foreign_key(
        "audit_log_admin_id_fkey", "audit_log", "admin_user", ["admin_id"], ["id"]
    )
    op.alter_column("audit_log", "admin_id", nullable=False)
