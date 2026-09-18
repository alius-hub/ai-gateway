"""Initial schema baseline.

Revision ID: 20260901_0001
Revises:
Create Date: 2026-09-01 00:00:01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260901_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=128), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("nickname", sa.String(length=64), nullable=True),
        sa.Column("avatar_url", sa.String(length=255), nullable=True),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.create_table(
        "organizations",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("owner_user_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
    )
    op.create_index("ix_organizations_code", "organizations", ["code"], unique=True)

    op.create_table(
        "projects",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("environment", sa.String(length=32), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.BigInteger(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
    )
    op.create_index("ix_projects_code", "projects", ["code"], unique=False)
    op.create_index("ix_projects_organization_id", "projects", ["organization_id"], unique=False)

    op.create_table(
        "providers",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("organization_id", sa.BigInteger(), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("provider_type", sa.String(length=64), nullable=False),
        sa.Column("base_url", sa.String(length=255), nullable=False),
        sa.Column("api_key_ciphertext", sa.Text(), nullable=True),
        sa.Column("extra_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("health_status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
    )
    op.create_index("ix_providers_code", "providers", ["code"], unique=False)

    op.create_table(
        "aggregated_models",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("organization_id", sa.BigInteger(), nullable=True),
        sa.Column("aggregate_model_code", sa.String(length=128), nullable=False),
        sa.Column("public_model_name", sa.String(length=128), nullable=False),
        sa.Column("model_type", sa.String(length=32), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("capabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("default_routing_strategy", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
    )
    op.create_index(
        "ix_aggregated_models_aggregate_model_code",
        "aggregated_models",
        ["aggregate_model_code"],
        unique=True,
    )
    op.create_index(
        "ix_aggregated_models_model_type", "aggregated_models", ["model_type"], unique=False
    )
    op.create_index(
        "ix_aggregated_models_public_model_name",
        "aggregated_models",
        ["public_model_name"],
        unique=False,
    )

    op.create_table(
        "api_keys",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("project_id", sa.BigInteger(), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("key_prefix", sa.String(length=32), nullable=False),
        sa.Column("key_hash", sa.String(length=255), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("allowed_ips", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("allowed_models", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"], unique=True)
    op.create_index("ix_api_keys_organization_id", "api_keys", ["organization_id"], unique=False)

    op.create_table(
        "provider_models",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("provider_id", sa.BigInteger(), nullable=False),
        sa.Column("access_model_code", sa.String(length=128), nullable=False),
        sa.Column("provider_model_name", sa.String(length=128), nullable=False),
        sa.Column("model_type", sa.String(length=32), nullable=False),
        sa.Column("context_window", sa.Integer(), nullable=True),
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
        sa.Column("input_price", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("output_price", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("currency", sa.String(length=16), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"]),
    )
    op.create_index(
        "ix_provider_models_access_model_code",
        "provider_models",
        ["access_model_code"],
        unique=False,
    )
    op.create_index("ix_provider_models_model_type", "provider_models", ["model_type"], unique=False)
    op.create_index(
        "ix_provider_models_provider_id", "provider_models", ["provider_id"], unique=False
    )

    op.create_table(
        "model_nodes",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("provider_id", sa.BigInteger(), nullable=False),
        sa.Column("provider_model_id", sa.BigInteger(), nullable=False),
        sa.Column("node_code", sa.String(length=64), nullable=False),
        sa.Column("node_name", sa.String(length=128), nullable=False),
        sa.Column("model_type", sa.String(length=32), nullable=False),
        sa.Column("endpoint_url", sa.String(length=255), nullable=False),
        sa.Column("region", sa.String(length=64), nullable=True),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("health_status", sa.String(length=32), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("max_concurrency", sa.Integer(), nullable=False),
        sa.Column("max_requests_per_second", sa.Integer(), nullable=True),
        sa.Column("max_requests_per_minute", sa.Integer(), nullable=True),
        sa.Column("max_tokens_per_minute", sa.BigInteger(), nullable=True),
        sa.Column("max_tokens_per_day", sa.BigInteger(), nullable=True),
        sa.Column("timeout_ms", sa.Integer(), nullable=False),
        sa.Column("circuit_breaker_status", sa.String(length=32), nullable=False),
        sa.Column("extra_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"]),
        sa.ForeignKeyConstraint(["provider_model_id"], ["provider_models.id"]),
    )
    op.create_index("ix_model_nodes_model_type", "model_nodes", ["model_type"], unique=False)
    op.create_index("ix_model_nodes_node_code", "model_nodes", ["node_code"], unique=True)
    op.create_index("ix_model_nodes_provider_id", "model_nodes", ["provider_id"], unique=False)
    op.create_index(
        "ix_model_nodes_provider_model_id", "model_nodes", ["provider_model_id"], unique=False
    )

    op.create_table(
        "aggregate_model_node_bindings",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("aggregate_model_id", sa.BigInteger(), nullable=False),
        sa.Column("node_id", sa.BigInteger(), nullable=False),
        sa.Column("traffic_role", sa.String(length=32), nullable=False),
        sa.Column("route_priority", sa.Integer(), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("gray_percent", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("capability_tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("route_conditions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("is_fallback", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["aggregate_model_id"], ["aggregated_models.id"]),
        sa.ForeignKeyConstraint(["node_id"], ["model_nodes.id"]),
    )
    op.create_index(
        "ix_aggregate_model_node_bindings_aggregate_model_id",
        "aggregate_model_node_bindings",
        ["aggregate_model_id"],
        unique=False,
    )
    op.create_index(
        "ix_aggregate_model_node_bindings_node_id",
        "aggregate_model_node_bindings",
        ["node_id"],
        unique=False,
    )

    op.create_table(
        "project_model_policies",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("aggregate_model_id", sa.BigInteger(), nullable=False),
        sa.Column("public_model_name", sa.String(length=128), nullable=False),
        sa.Column("model_type", sa.String(length=32), nullable=False),
        sa.Column("is_visible", sa.Boolean(), nullable=False),
        sa.Column("node_id", sa.BigInteger(), nullable=True),
        sa.Column("route_priority", sa.Integer(), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("max_requests_per_minute", sa.Integer(), nullable=True),
        sa.Column("max_tokens_per_day", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["aggregate_model_id"], ["aggregated_models.id"]),
        sa.ForeignKeyConstraint(["node_id"], ["model_nodes.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
    )
    op.create_index(
        "ix_project_model_policies_aggregate_model_id",
        "project_model_policies",
        ["aggregate_model_id"],
        unique=False,
    )
    op.create_index(
        "ix_project_model_policies_model_type",
        "project_model_policies",
        ["model_type"],
        unique=False,
    )
    op.create_index(
        "ix_project_model_policies_project_id",
        "project_model_policies",
        ["project_id"],
        unique=False,
    )

    op.create_table(
        "request_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("api_key_id", sa.BigInteger(), nullable=True),
        sa.Column("aggregate_model_id", sa.BigInteger(), nullable=True),
        sa.Column("provider_id", sa.BigInteger(), nullable=True),
        sa.Column("provider_model_id", sa.BigInteger(), nullable=True),
        sa.Column("node_id", sa.BigInteger(), nullable=True),
        sa.Column("public_model_name", sa.String(length=128), nullable=False),
        sa.Column("model_type", sa.String(length=32), nullable=False),
        sa.Column("endpoint", sa.String(length=128), nullable=False),
        sa.Column("request_method", sa.String(length=16), nullable=False),
        sa.Column("requester_ip", sa.String(length=64), nullable=False),
        sa.Column("request_body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=False),
        sa.Column("provider_status", sa.String(length=32), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["aggregate_model_id"], ["aggregated_models.id"]),
        sa.ForeignKeyConstraint(["api_key_id"], ["api_keys.id"]),
        sa.ForeignKeyConstraint(["node_id"], ["model_nodes.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"]),
        sa.ForeignKeyConstraint(["provider_model_id"], ["provider_models.id"]),
    )
    op.create_index("ix_request_logs_organization_id", "request_logs", ["organization_id"], unique=False)
    op.create_index("ix_request_logs_project_id", "request_logs", ["project_id"], unique=False)
    op.create_index("ix_request_logs_request_id", "request_logs", ["request_id"], unique=True)

    op.create_table(
        "usage_records",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("request_log_id", sa.BigInteger(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("api_key_id", sa.BigInteger(), nullable=True),
        sa.Column("aggregate_model_id", sa.BigInteger(), nullable=True),
        sa.Column("provider_id", sa.BigInteger(), nullable=True),
        sa.Column("provider_model_id", sa.BigInteger(), nullable=True),
        sa.Column("node_id", sa.BigInteger(), nullable=True),
        sa.Column("model_type", sa.String(length=32), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("currency", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["aggregate_model_id"], ["aggregated_models.id"]),
        sa.ForeignKeyConstraint(["api_key_id"], ["api_keys.id"]),
        sa.ForeignKeyConstraint(["node_id"], ["model_nodes.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"]),
        sa.ForeignKeyConstraint(["provider_model_id"], ["provider_models.id"]),
        sa.ForeignKeyConstraint(["request_log_id"], ["request_logs.id"]),
    )
    op.create_index("ix_usage_records_organization_id", "usage_records", ["organization_id"], unique=False)
    op.create_index("ix_usage_records_project_id", "usage_records", ["project_id"], unique=False)
    op.create_index("ix_usage_records_request_log_id", "usage_records", ["request_log_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_usage_records_request_log_id", table_name="usage_records")
    op.drop_index("ix_usage_records_project_id", table_name="usage_records")
    op.drop_index("ix_usage_records_organization_id", table_name="usage_records")
    op.drop_table("usage_records")

    op.drop_index("ix_request_logs_request_id", table_name="request_logs")
    op.drop_index("ix_request_logs_project_id", table_name="request_logs")
    op.drop_index("ix_request_logs_organization_id", table_name="request_logs")
    op.drop_table("request_logs")

    op.drop_index("ix_project_model_policies_project_id", table_name="project_model_policies")
    op.drop_index("ix_project_model_policies_model_type", table_name="project_model_policies")
    op.drop_index(
        "ix_project_model_policies_aggregate_model_id",
        table_name="project_model_policies",
    )
    op.drop_table("project_model_policies")

    op.drop_index(
        "ix_aggregate_model_node_bindings_node_id",
        table_name="aggregate_model_node_bindings",
    )
    op.drop_index(
        "ix_aggregate_model_node_bindings_aggregate_model_id",
        table_name="aggregate_model_node_bindings",
    )
    op.drop_table("aggregate_model_node_bindings")

    op.drop_index("ix_model_nodes_provider_model_id", table_name="model_nodes")
    op.drop_index("ix_model_nodes_provider_id", table_name="model_nodes")
    op.drop_index("ix_model_nodes_node_code", table_name="model_nodes")
    op.drop_index("ix_model_nodes_model_type", table_name="model_nodes")
    op.drop_table("model_nodes")

    op.drop_index("ix_provider_models_provider_id", table_name="provider_models")
    op.drop_index("ix_provider_models_model_type", table_name="provider_models")
    op.drop_index("ix_provider_models_access_model_code", table_name="provider_models")
    op.drop_table("provider_models")

    op.drop_index("ix_api_keys_organization_id", table_name="api_keys")
    op.drop_index("ix_api_keys_key_hash", table_name="api_keys")
    op.drop_table("api_keys")

    op.drop_index(
        "ix_aggregated_models_public_model_name",
        table_name="aggregated_models",
    )
    op.drop_index("ix_aggregated_models_model_type", table_name="aggregated_models")
    op.drop_index(
        "ix_aggregated_models_aggregate_model_code",
        table_name="aggregated_models",
    )
    op.drop_table("aggregated_models")

    op.drop_index("ix_providers_code", table_name="providers")
    op.drop_table("providers")

    op.drop_index("ix_projects_organization_id", table_name="projects")
    op.drop_index("ix_projects_code", table_name="projects")
    op.drop_table("projects")

    op.drop_index("ix_organizations_code", table_name="organizations")
    op.drop_table("organizations")

    op.drop_index("ix_users_username", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
