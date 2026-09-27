"""Organization hierarchy and group role.

Revision ID: 20260926_0003
Revises: 20260926_0002
"""

from alembic import op
import sqlalchemy as sa

revision = "20260926_0003"
down_revision = "20260926_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("parent_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_organizations_parent_id", "organizations", "organizations", ["parent_id"], ["id"]
    )
    op.create_index("ix_organizations_parent_id", "organizations", ["parent_id"])
    op.add_column(
        "user_groups",
        sa.Column("role", sa.String(32), nullable=False, server_default="member"),
    )


def downgrade() -> None:
    op.drop_column("user_groups", "role")
    op.drop_index("ix_organizations_parent_id", table_name="organizations")
    op.drop_constraint("fk_organizations_parent_id", "organizations", type_="foreignkey")
    op.drop_column("organizations", "parent_id")
