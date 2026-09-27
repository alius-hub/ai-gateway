"""Allow platform-level projects without an organization.

Revision ID: 20260926_0005
Revises: 20260926_0004
"""

from alembic import op
import sqlalchemy as sa

revision = "20260926_0005"
down_revision = "20260926_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("projects", "organization_id", existing_type=sa.BigInteger(), nullable=True)


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(sa.text(
        "SELECT 1 FROM projects WHERE organization_id IS NULL LIMIT 1"
    )).first():
        raise RuntimeError("存在平台级项目，无法恢复组织必填约束。")
    op.alter_column("projects", "organization_id", existing_type=sa.BigInteger(), nullable=False)
