"""Add call latency and reasoning usage metrics.

Revision ID: 20260928_0020
Revises: 20260928_0019
"""

import sqlalchemy as sa
from alembic import op

revision = "20260928_0020"
down_revision = "20260928_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("request_logs", sa.Column("ttft_ms", sa.Integer(), nullable=True))
    op.add_column("request_logs", sa.Column("tpot_ms", sa.Numeric(12, 3), nullable=True))
    op.add_column("usage_records", sa.Column("reasoning_tokens", sa.Integer(), nullable=True))
    op.add_column("usage_records", sa.Column("non_reasoning_tokens", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("usage_records", "non_reasoning_tokens")
    op.drop_column("usage_records", "reasoning_tokens")
    op.drop_column("request_logs", "tpot_ms")
    op.drop_column("request_logs", "ttft_ms")
