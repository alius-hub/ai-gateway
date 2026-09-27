"""Identity management tables and generated identifiers.

Revision ID: 20260926_0002
Revises: 20260901_0001
"""

from alembic import op
import sqlalchemy as sa

revision = "20260926_0002"
down_revision = "20260901_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("users", "organizations", "projects"):
        op.execute(
            f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
            f"COALESCE((SELECT MAX(id) FROM {table}), 0) + 1, false)"
        )
    op.create_table(
        "user_groups",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("organization_id", sa.BigInteger(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("group_name", sa.String(128), nullable=False),
        sa.Column("group_code", sa.String(64), nullable=False),
        sa.Column("description", sa.String(255)),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "group_code"),
    )
    for table, parent_column, parent_table in (
        ("organization_members", "organization_id", "organizations"),
        ("project_members", "project_id", "projects"),
        ("user_group_members", "group_id", "user_groups"),
    ):
        columns = [
            sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
            sa.Column(parent_column, sa.BigInteger(), sa.ForeignKey(f"{parent_table}.id"), nullable=False),
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        ]
        if table != "user_group_members":
            columns.extend(
                [
                    sa.Column("role", sa.String(32), nullable=False),
                    sa.Column("status", sa.Integer(), nullable=False),
                ]
            )
        op.create_table(table, *columns, sa.UniqueConstraint(parent_column, "user_id"))


def downgrade() -> None:
    for table in ("user_group_members", "project_members", "organization_members", "user_groups"):
        op.drop_table(table)
    for table in ("projects", "organizations", "users"):
        op.execute(f"ALTER TABLE {table} ALTER COLUMN id DROP IDENTITY IF EXISTS")
