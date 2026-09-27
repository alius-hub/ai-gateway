"""Separate model-independent routing workflows from aggregate model bindings.

Revision ID: 20260927_0010
Revises: 20260926_0009
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260927_0010"
down_revision = "20260926_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("routing_workflows", "model_type", existing_type=sa.String(32), nullable=True)
    op.add_column("aggregated_models", sa.Column("workflow_bindings", JSONB(), nullable=True))


def downgrade() -> None:
    if op.get_bind().execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM routing_workflows WHERE model_type IS NULL)"
    )).scalar():
        raise RuntimeError("先处理无模型类型的流程，再回退此迁移。")
    op.drop_column("aggregated_models", "workflow_bindings")
    op.alter_column("routing_workflows", "model_type", existing_type=sa.String(32), nullable=False)
