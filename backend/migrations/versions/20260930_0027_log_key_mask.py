"""Store the masked API key used by each request."""

import sqlalchemy as sa
from alembic import op

revision = "20260930_0027"
down_revision = "20260930_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("request_logs", sa.Column("api_key_masked", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("request_logs", "api_key_masked")
