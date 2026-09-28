"""Allow aggregate requests to retry another candidate after upstream failure.

Revision ID: 20260928_0022
Revises: 20260928_0021
"""

import sqlalchemy as sa
from alembic import op

revision = "20260928_0022"
down_revision = "20260928_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("aggregated_models", sa.Column(
        "retry_on_failure", sa.Boolean(), nullable=False, server_default=sa.false(),
    ))


def downgrade() -> None:
    op.drop_column("aggregated_models", "retry_on_failure")
