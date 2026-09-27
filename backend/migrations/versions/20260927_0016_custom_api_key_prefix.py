"""Allow per-key custom prefixes that survive rotation.

Revision ID: 20260927_0016
Revises: 20260927_0015
"""

import sqlalchemy as sa
from alembic import op

revision = "20260927_0016"
down_revision = "20260927_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("api_keys", sa.Column("custom_prefix", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("api_keys", "custom_prefix")
