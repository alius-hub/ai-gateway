"""Add per-rule recipients and independent delivery records."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260930_0026"
down_revision = "20260930_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("alert_rules", "alert_events"):
        op.add_column(table, sa.Column(
            "recipients", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb"),
        ))
    op.add_column("alert_deliveries", sa.Column(
        "receive_id_type", sa.String(16), nullable=False, server_default="chat_id",
    ))
    op.add_column("alert_deliveries", sa.Column(
        "receive_id", sa.String(128), nullable=False, server_default="",
    ))
    op.execute("""
        UPDATE alert_deliveries SET receive_id = COALESCE(
            (SELECT chat_id FROM feishu_settings WHERE id = 1), '')
    """)
    op.execute("""
        UPDATE alert_events SET recipients = jsonb_build_array(jsonb_build_object(
            'receive_id_type', 'chat_id', 'receive_id', COALESCE(
                (SELECT chat_id FROM feishu_settings WHERE id = 1), '')))
    """)
    op.drop_constraint("alert_deliveries_event_id_kind_key", "alert_deliveries", type_="unique")
    op.create_unique_constraint("uq_alert_delivery_target", "alert_deliveries", [
        "event_id", "kind", "receive_id_type", "receive_id",
    ])


def downgrade() -> None:
    # Retain one historical delivery per kind before restoring the old constraint.
    op.execute("""
        DELETE FROM alert_deliveries a USING alert_deliveries b
        WHERE a.event_id = b.event_id AND a.kind = b.kind AND a.id > b.id
    """)
    op.drop_constraint("uq_alert_delivery_target", "alert_deliveries", type_="unique")
    op.create_unique_constraint("alert_deliveries_event_id_kind_key", "alert_deliveries",
                                ["event_id", "kind"])
    op.drop_column("alert_deliveries", "receive_id")
    op.drop_column("alert_deliveries", "receive_id_type")
    for table in ("alert_events", "alert_rules"):
        op.drop_column(table, "recipients")
