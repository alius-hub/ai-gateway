"""Add reusable routing workflows to aggregated models.

Revision ID: 20260926_0009
Revises: 20260926_0008
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260926_0009"
down_revision = "20260926_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "routing_workflows",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("model_type", sa.String(32), nullable=False),
        sa.Column("definition", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_routing_workflows_model_type", "routing_workflows", ["model_type"])
    op.add_column("aggregated_models", sa.Column("workflow_id", sa.BigInteger(), nullable=True))
    op.create_index("ix_aggregated_models_workflow_id", "aggregated_models", ["workflow_id"])
    op.create_foreign_key(
        "fk_aggregated_models_workflow_id", "aggregated_models",
        "routing_workflows", ["workflow_id"], ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_aggregated_models_workflow_id", "aggregated_models", type_="foreignkey")
    op.drop_index("ix_aggregated_models_workflow_id", table_name="aggregated_models")
    op.drop_column("aggregated_models", "workflow_id")
    op.drop_index("ix_routing_workflows_model_type", table_name="routing_workflows")
    op.drop_table("routing_workflows")
