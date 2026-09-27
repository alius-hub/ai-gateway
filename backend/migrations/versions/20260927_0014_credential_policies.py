"""Add administrator-managed credential policy settings.

Revision ID: 20260927_0014
Revises: 20260927_0013
"""

import sqlalchemy as sa
from alembic import op

revision = "20260927_0014"
down_revision = "20260927_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("api_keys", "organization_id", existing_type=sa.BigInteger(), nullable=True)
    for table in ("request_logs", "usage_records"):
        op.alter_column(table, "organization_id", existing_type=sa.BigInteger(), nullable=True)
        op.alter_column(table, "project_id", existing_type=sa.BigInteger(), nullable=True)
    op.add_column("api_keys", sa.Column("tpm_limit", sa.BigInteger(), nullable=True))
    op.add_column("api_keys", sa.Column("qps_limit", sa.Integer(), nullable=True))
    op.add_column("api_keys", sa.Column("token_budget", sa.BigInteger(), nullable=True))
    op.add_column("api_keys", sa.Column("budget_period", sa.String(16), nullable=True))
    op.add_column("api_keys", sa.Column(
        "wait_mode", sa.String(16), nullable=False, server_default="block",
    ))
    op.add_column("api_keys", sa.Column(
        "max_wait_ms", sa.Integer(), nullable=False, server_default="30000",
    ))


def downgrade() -> None:
    op.drop_column("api_keys", "max_wait_ms")
    op.drop_column("api_keys", "wait_mode")
    op.drop_column("api_keys", "budget_period")
    op.drop_column("api_keys", "token_budget")
    op.drop_column("api_keys", "qps_limit")
    op.drop_column("api_keys", "tpm_limit")
    # Existing platform-level projects or personal keys can have NULL scopes.
    # Restoring NOT NULL requires migrating those records first.
