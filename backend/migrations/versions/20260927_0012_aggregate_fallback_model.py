"""Add an optional fallback access model to aggregated models.

Revision ID: 20260927_0012
Revises: 20260927_0011
"""

from alembic import op
import sqlalchemy as sa

revision = "20260927_0012"
down_revision = "20260927_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "aggregated_models",
        sa.Column("fallback_model_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_aggregated_models_fallback_model_id",
        "aggregated_models", "provider_models",
        ["fallback_model_id"], ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_aggregated_models_fallback_model_id", "aggregated_models", type_="foreignkey")
    op.drop_column("aggregated_models", "fallback_model_id")
