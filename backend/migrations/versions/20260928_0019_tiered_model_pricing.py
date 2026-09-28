"""Add optional input and output token-length price tiers.

Revision ID: 20260928_0019
Revises: 20260928_0018
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260928_0019"
down_revision = "20260928_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("provider_models", sa.Column(
        "tiered_pricing", sa.Boolean(), nullable=False, server_default=sa.false(),
    ))
    op.add_column("provider_models", sa.Column("input_price_tiers", JSONB(), nullable=True))
    op.add_column("provider_models", sa.Column("output_price_tiers", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("provider_models", "output_price_tiers")
    op.drop_column("provider_models", "input_price_tiers")
    op.drop_column("provider_models", "tiered_pricing")
