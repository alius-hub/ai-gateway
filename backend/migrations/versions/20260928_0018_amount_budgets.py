"""Price access models in CNY and add shared project and key budgets.

Revision ID: 20260928_0018
Revises: 20260927_0017
"""

import sqlalchemy as sa
from alembic import op

revision = "20260928_0018"
down_revision = "20260927_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("provider_models", sa.Column("price_unit_k", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("projects", sa.Column("amount_budget", sa.Numeric(18, 2), nullable=True))
    op.add_column("api_keys", sa.Column("amount_budget", sa.Numeric(18, 2), nullable=True))
    # Preserve legacy USD prices; they require explicit repricing before budgeted use.
    op.execute("UPDATE provider_models SET currency = 'CNY' WHERE input_price IS NULL AND output_price IS NULL")
    op.alter_column("provider_models", "currency", server_default="CNY")
    op.alter_column("usage_records", "currency", server_default="CNY")


def downgrade() -> None:
    op.alter_column("usage_records", "currency", server_default="USD")
    op.alter_column("provider_models", "currency", server_default="USD")
    op.drop_column("api_keys", "amount_budget")
    op.drop_column("projects", "amount_budget")
    op.drop_column("provider_models", "price_unit_k")
