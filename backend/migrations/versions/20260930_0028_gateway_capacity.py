"""Incremental spend totals and quota lookup indexes."""

import sqlalchemy as sa
from alembic import op

revision = "20260930_0028"
down_revision = "20260930_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gateway_spend",
        sa.Column("scope", sa.String(16), primary_key=True),
        sa.Column("scope_id", sa.BigInteger(), primary_key=True),
        sa.Column("period_kind", sa.String(16), primary_key=True),
        sa.Column("period_stamp", sa.String(8), primary_key=True),
        sa.Column("spent_cents", sa.BigInteger(), nullable=False),
    )
    # Run with gateway traffic stopped: backfill and new writers must not overlap.
    op.execute("""
        INSERT INTO gateway_spend
        SELECT 'project', project_id, 'all', 'all',
               ROUND(SUM(estimated_cost) * 100)::bigint
        FROM usage_records
        WHERE currency = 'CNY' AND project_id IS NOT NULL
              AND estimated_cost IS NOT NULL
        GROUP BY project_id
    """)
    for kind in ("week", "month"):
        op.execute(sa.text(f"""
            INSERT INTO gateway_spend
            SELECT 'key', api_key_id, '{kind}',
                   TO_CHAR(DATE_TRUNC('{kind}', created_at), 'YYYYMMDD'),
                   ROUND(SUM(estimated_cost) * 100)::bigint
            FROM usage_records
            WHERE currency = 'CNY' AND api_key_id IS NOT NULL
                  AND estimated_cost IS NOT NULL
            GROUP BY api_key_id, DATE_TRUNC('{kind}', created_at)
        """))
    op.create_index("ix_usage_records_key_created_at", "usage_records",
                    ["api_key_id", "created_at"])
    op.create_index("ix_api_keys_scope_project_id", "api_keys",
                    ["scope_type", "project_id", "id"])
    op.create_index("ix_api_keys_scope_user_id", "api_keys", ["scope_type", "user_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_api_keys_scope_user_id", table_name="api_keys")
    op.drop_index("ix_api_keys_scope_project_id", table_name="api_keys")
    op.drop_index("ix_usage_records_key_created_at", table_name="usage_records")
    op.drop_table("gateway_spend")
