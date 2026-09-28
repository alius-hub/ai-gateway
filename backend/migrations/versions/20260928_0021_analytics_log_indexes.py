"""Add time range indexes for analytics queries.

Revision ID: 20260928_0021
Revises: 20260928_0020
"""

from alembic import op

revision = "20260928_0021"
down_revision = "20260928_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_request_logs_created_at", "request_logs", ["created_at"])
    op.create_index("ix_request_logs_project_created_at", "request_logs",
                    ["project_id", "created_at"])
    op.create_index("ix_request_logs_provider_created_at", "request_logs",
                    ["provider_id", "created_at"])
    op.create_index("ix_request_logs_model_created_at", "request_logs",
                    ["provider_model_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_request_logs_model_created_at", table_name="request_logs")
    op.drop_index("ix_request_logs_provider_created_at", table_name="request_logs")
    op.drop_index("ix_request_logs_project_created_at", table_name="request_logs")
    op.drop_index("ix_request_logs_created_at", table_name="request_logs")
