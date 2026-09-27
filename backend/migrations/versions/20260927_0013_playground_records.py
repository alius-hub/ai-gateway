"""Persist per-user online debugging records.

Revision ID: 20260927_0013
Revises: 20260927_0012
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260927_0013"
down_revision = "20260927_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "playground_records",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("model_code", sa.String(128), nullable=False),
        sa.Column("protocol", sa.String(32), nullable=False),
        sa.Column("stream", sa.Boolean(), nullable=False),
        sa.Column("request_url", sa.Text(), nullable=False),
        sa.Column("request_headers", JSONB(), nullable=False),
        sa.Column("request_body", JSONB(), nullable=False),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_playground_records_user_id", "playground_records", ["user_id"])
    op.create_index("ix_playground_records_created_at", "playground_records", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_playground_records_created_at", table_name="playground_records")
    op.drop_index("ix_playground_records_user_id", table_name="playground_records")
    op.drop_table("playground_records")
