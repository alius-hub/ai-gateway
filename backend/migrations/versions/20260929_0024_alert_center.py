"""Add alert rules, incidents and Feishu app delivery.

Revision ID: 20260929_0024
Revises: 20260929_0023
"""

import sqlalchemy as sa
from alembic import op

revision = "20260929_0024"
down_revision = "20260929_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feishu_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("app_id", sa.String(128), nullable=False),
        sa.Column("app_secret_ciphertext", sa.Text(), nullable=False),
        sa.Column("chat_id", sa.String(128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "alert_rules",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("metric", sa.String(32), nullable=False),
        sa.Column("scope_id", sa.BigInteger(), nullable=True),
        sa.Column("threshold", sa.Numeric(8, 2), nullable=False),
        sa.Column("window_minutes", sa.Integer(), nullable=False),
        sa.Column("min_samples", sa.Integer(), nullable=False),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        "alert_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("rule_id", sa.BigInteger(), sa.ForeignKey("alert_rules.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("current_value", sa.Numeric(12, 2), nullable=False),
        sa.Column("threshold", sa.Numeric(8, 2), nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.BigInteger(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_alert_events_rule_id", "alert_events", ["rule_id"])
    op.create_index("ix_alert_events_status", "alert_events", ["status"])
    op.create_index(
        "uq_alert_events_active_rule", "alert_events", ["rule_id"],
        unique=True, postgresql_where=sa.text("status IN ('open', 'acknowledged')"),
    )
    op.create_table(
        "alert_deliveries",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.BigInteger(), sa.ForeignKey("alert_events.id"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("current_value", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.String(255), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("event_id", "kind"),
    )
    op.create_index("ix_alert_deliveries_event_id", "alert_deliveries", ["event_id"])
    op.create_index("ix_alert_deliveries_due", "alert_deliveries", ["status", "next_attempt_at"])


def downgrade() -> None:
    op.drop_table("alert_deliveries")
    op.drop_table("alert_events")
    op.drop_table("alert_rules")
    op.drop_table("feishu_settings")
