"""Add editable platform admin flag for users.

Revision ID: 20260926_0006
Revises: 20260926_0005
"""

from alembic import op
import sqlalchemy as sa

revision = "20260926_0006"
down_revision = "20260926_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("is_platform_admin", sa.Integer(), nullable=False, server_default="0"))
    connection = op.get_bind()
    connection.execute(sa.text(
        "UPDATE users SET is_platform_admin = 1 WHERE username = 'admin'"
    ))
    op.alter_column("users", "is_platform_admin", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "is_platform_admin")
