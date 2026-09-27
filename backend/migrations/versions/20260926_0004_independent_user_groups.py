"""Make user groups independent of organizations.

Revision ID: 20260926_0004
Revises: 20260926_0003
"""

from alembic import op
import sqlalchemy as sa

revision = "20260926_0004"
down_revision = "20260926_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep historical scopes for audit and for a possible rollback before new groups are created.
    op.create_table(
        "user_group_legacy_scope",
        sa.Column("group_id", sa.BigInteger(), primary_key=True),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
    )
    op.execute(
        "INSERT INTO user_group_legacy_scope (group_id, organization_id, role) "
        "SELECT id, organization_id, role FROM user_groups"
    )
    op.drop_constraint("user_groups_organization_id_group_code_key", "user_groups", type_="unique")
    op.drop_constraint("user_groups_organization_id_fkey", "user_groups", type_="foreignkey")
    op.drop_column("user_groups", "organization_id")
    op.drop_column("user_groups", "role")


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(sa.text(
        "SELECT 1 FROM user_groups g LEFT JOIN user_group_legacy_scope s ON s.group_id = g.id "
        "WHERE s.group_id IS NULL LIMIT 1"
    )).first():
        raise RuntimeError("存在独立用户组，无法恢复其原本不存在的组织归属。")
    op.add_column("user_groups", sa.Column("organization_id", sa.BigInteger(), nullable=True))
    op.add_column("user_groups", sa.Column("role", sa.String(32), nullable=True))
    op.execute(
        "UPDATE user_groups SET organization_id = s.organization_id, role = s.role "
        "FROM user_group_legacy_scope s WHERE user_groups.id = s.group_id"
    )
    op.alter_column("user_groups", "organization_id", nullable=False)
    op.alter_column("user_groups", "role", nullable=False)
    op.create_foreign_key(
        "user_groups_organization_id_fkey", "user_groups", "organizations", ["organization_id"], ["id"]
    )
    op.create_unique_constraint(
        "user_groups_organization_id_group_code_key", "user_groups", ["organization_id", "group_code"]
    )
    op.drop_table("user_group_legacy_scope")
