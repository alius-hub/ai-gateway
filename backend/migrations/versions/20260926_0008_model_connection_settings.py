"""Store model-specific connection and capacity settings.

Revision ID: 20260926_0008
Revises: 20260926_0007
"""

from alembic import op
import sqlalchemy as sa

revision = "20260926_0008"
down_revision = "20260926_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("provider_models", sa.Column("base_url", sa.String(255), nullable=True))
    op.add_column("provider_models", sa.Column("region", sa.String(64), nullable=True))
    op.add_column("provider_models", sa.Column("max_concurrency", sa.Integer(), nullable=True))
    op.add_column("provider_models", sa.Column("timeout_ms", sa.Integer(), nullable=True))
    connection = op.get_bind()
    connection.execute(sa.text("""
        UPDATE provider_models AS m
        SET base_url = p.base_url
        FROM provider_protocols AS p
        WHERE p.id = m.protocol_id
    """))


def downgrade() -> None:
    op.drop_column("provider_models", "timeout_ms")
    op.drop_column("provider_models", "max_concurrency")
    op.drop_column("provider_models", "region")
    op.drop_column("provider_models", "base_url")
