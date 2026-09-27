"""Store direct candidate models on aggregated models.

Revision ID: 20260927_0011
Revises: 20260927_0010
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260927_0011"
down_revision = "20260927_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("aggregated_models", sa.Column("routing_model_ids", JSONB(), nullable=True))


def downgrade() -> None:
    if op.get_bind().execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM aggregated_models WHERE routing_model_ids IS NOT NULL)"
    )).scalar():
        raise RuntimeError("先处理直接绑定候选模型的聚合配置，再回退此迁移。")
    op.drop_column("aggregated_models", "routing_model_ids")
