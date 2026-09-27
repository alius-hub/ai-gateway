"""Add a global policy for external image archival.

Revision ID: 20260927_0017
Revises: 20260927_0016
"""

import sqlalchemy as sa
from alembic import op

revision = "20260927_0017"
down_revision = "20260927_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gateway_log_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("image_mode", sa.String(24), nullable=False,
                  server_default="content_only"),
    )
    op.execute("INSERT INTO gateway_log_settings (id, image_mode) VALUES (1, 'content_only')")


def downgrade() -> None:
    op.drop_table("gateway_log_settings")
