"""Suppress manually resolved alerts until the metric recovers."""

import sqlalchemy as sa
from alembic import op

revision = "20260930_0025"
down_revision = "20260929_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("alert_rules", sa.Column(
        "suppressed_until_recovery", sa.Boolean(), nullable=False, server_default=sa.false(),
    ))


def downgrade() -> None:
    op.drop_column("alert_rules", "suppressed_until_recovery")
