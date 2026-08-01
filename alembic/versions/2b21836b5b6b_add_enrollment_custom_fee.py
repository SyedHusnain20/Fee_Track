"""add enrollment custom_fee

Revision ID: 2b21836b5b6b
Revises: b6d1f84a2c93
Create Date: 2026-08-01 00:00:00.000000

Lets the admin set a one-off custom fee for a specific enrollment
directly from the "Enroll in" checklist on students/form.html, instead
of always billing every enrollment at its category's live band rate.

Nullable, and left NULL by default -- an existing enrollment (or a new
one where the admin leaves the fee field blank) keeps behaving exactly
as before this column existed: priced live off CategoryFeeDefault via
app.services.fees.get_band_fee. Only once an admin explicitly fills in a
custom amount does this override kick in, and only for that one
enrollment -- it does not touch the category's shared default_amount, so
every other student in that band is unaffected. See
app.services.fees.get_enrollment_amount, the single place this should be
read from.
"""
from alembic import op
import sqlalchemy as sa

revision = "2b21836b5b6b"
down_revision = "b6d1f84a2c93"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("enrollment", sa.Column("custom_fee", sa.Numeric(10, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("enrollment", "custom_fee")
