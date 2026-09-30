from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    nickname: Mapped[str | None] = mapped_column(String(64), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_platform_admin: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[int] = mapped_column(Integer, default=1)
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    actor_username: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(32), index=True)
    resource: Mapped[str] = mapped_column(String(128), index=True)
    method: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(String(512))
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status_code: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True,
    )


class Organization(TimestampMixin, Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[int] = mapped_column(Integer, default=1)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    code: Mapped[str] = mapped_column(String(64), index=True)
    environment: Mapped[str] = mapped_column(String(32), default="dev")
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[int] = mapped_column(Integer, default=1)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    amount_budget: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)


class UserGroup(TimestampMixin, Base):
    __tablename__ = "user_groups"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    group_name: Mapped[str] = mapped_column(String(128))
    group_code: Mapped[str] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))


class OrganizationMember(TimestampMixin, Base):
    __tablename__ = "organization_members"
    __table_args__ = (UniqueConstraint("organization_id", "user_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(32), default="member")
    status: Mapped[int] = mapped_column(Integer, default=1)


class ProjectMember(TimestampMixin, Base):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(32), default="developer")
    status: Mapped[int] = mapped_column(Integer, default=1)


class UserGroupMember(TimestampMixin, Base):
    __tablename__ = "user_group_members"
    __table_args__ = (UniqueConstraint("group_id", "user_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("user_groups.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))


class ApiKey(TimestampMixin, Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True,
    )
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    scope_type: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(128))
    key_prefix: Mapped[str] = mapped_column(String(32))
    custom_prefix: Mapped[str | None] = mapped_column(String(20), nullable=True)
    key_hash: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    key_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[int] = mapped_column(Integer, default=1)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    allowed_ips: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    allowed_models: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tpm_limit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    qps_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_budget: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    amount_budget: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    budget_period: Mapped[str | None] = mapped_column(String(16), nullable=True)
    wait_mode: Mapped[str] = mapped_column(String(16), default="block")
    max_wait_ms: Mapped[int] = mapped_column(Integer, default=30000)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)


class Provider(TimestampMixin, Base):
    __tablename__ = "providers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(128))
    code: Mapped[str] = mapped_column(String(64), index=True)
    provider_type: Mapped[str] = mapped_column(String(64))
    base_url: Mapped[str] = mapped_column(String(255))
    api_key_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[int] = mapped_column(Integer, default=1)
    health_status: Mapped[str] = mapped_column(String(32), default="unknown")


class ProviderProtocol(TimestampMixin, Base):
    __tablename__ = "provider_protocols"
    __table_args__ = (UniqueConstraint("provider_id", "code", name="uq_provider_protocol_code"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), index=True)
    code: Mapped[str] = mapped_column(String(64))
    protocol_type: Mapped[str] = mapped_column(String(64))
    base_url: Mapped[str] = mapped_column(String(255))
    status: Mapped[int] = mapped_column(Integer, default=1)


class ProviderSecret(TimestampMixin, Base):
    __tablename__ = "provider_secrets"
    __table_args__ = (UniqueConstraint("provider_id", "name", name="uq_provider_secret_name"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    ciphertext: Mapped[str] = mapped_column(Text)
    status: Mapped[int] = mapped_column(Integer, default=1)


class ProviderModel(TimestampMixin, Base):
    __tablename__ = "provider_models"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), index=True)
    protocol_id: Mapped[int | None] = mapped_column(
        ForeignKey("provider_protocols.id"), index=True, nullable=True)
    secret_id: Mapped[int | None] = mapped_column(
        ForeignKey("provider_secrets.id"), index=True, nullable=True)
    access_model_code: Mapped[str] = mapped_column(String(128), index=True)
    provider_model_name: Mapped[str] = mapped_column(String(128))
    model_type: Mapped[str] = mapped_column(String(32), index=True)
    base_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    region: Mapped[str | None] = mapped_column(String(64), nullable=True)
    max_concurrency: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timeout_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    context_window: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    output_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    price_unit_k: Mapped[int] = mapped_column(Integer, default=1)
    tiered_pricing: Mapped[bool] = mapped_column(Boolean, default=False)
    input_price_tiers: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    output_price_tiers: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    currency: Mapped[str] = mapped_column(String(16), default="CNY")
    status: Mapped[int] = mapped_column(Integer, default=1)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)


class ModelNode(TimestampMixin, Base):
    __tablename__ = "model_nodes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), index=True)
    provider_model_id: Mapped[int] = mapped_column(ForeignKey("provider_models.id"), index=True)
    node_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    node_name: Mapped[str] = mapped_column(String(128))
    model_type: Mapped[str] = mapped_column(String(32), index=True)
    endpoint_url: Mapped[str] = mapped_column(String(255))
    region: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[int] = mapped_column(Integer, default=1)
    health_status: Mapped[str] = mapped_column(String(32), default="healthy")
    weight: Mapped[int] = mapped_column(Integer, default=100)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    max_concurrency: Mapped[int] = mapped_column(Integer, default=10)
    max_requests_per_second: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_requests_per_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_tokens_per_minute: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    max_tokens_per_day: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    timeout_ms: Mapped[int] = mapped_column(Integer, default=60000)
    circuit_breaker_status: Mapped[str] = mapped_column(String(32), default="closed")
    extra_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class AggregatedModel(TimestampMixin, Base):
    __tablename__ = "aggregated_models"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    aggregate_model_code: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    public_model_name: Mapped[str] = mapped_column(String(128), index=True)
    model_type: Mapped[str] = mapped_column(String(32), index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    capabilities: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[int] = mapped_column(Integer, default=1)
    default_routing_strategy: Mapped[str] = mapped_column(String(32), default="priority")
    routing_model_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    fallback_model_id: Mapped[int | None] = mapped_column(ForeignKey("provider_models.id"), nullable=True)
    retry_on_failure: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    workflow_id: Mapped[int | None] = mapped_column(ForeignKey("routing_workflows.id"), nullable=True, index=True)
    workflow_bindings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class RoutingWorkflow(TimestampMixin, Base):
    __tablename__ = "routing_workflows"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_type: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    definition: Mapped[dict] = mapped_column(JSONB)


class AggregateModelNodeBinding(TimestampMixin, Base):
    __tablename__ = "aggregate_model_node_bindings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    aggregate_model_id: Mapped[int] = mapped_column(ForeignKey("aggregated_models.id"), index=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("model_nodes.id"), index=True)
    traffic_role: Mapped[str] = mapped_column(String(32), default="stable")
    route_priority: Mapped[int] = mapped_column(Integer, default=100)
    weight: Mapped[int] = mapped_column(Integer, default=100)
    gray_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    capability_tags: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    route_conditions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_fallback: Mapped[bool] = mapped_column(Boolean, default=False)


class ProjectModelPolicy(TimestampMixin, Base):
    __tablename__ = "project_model_policies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    aggregate_model_id: Mapped[int] = mapped_column(ForeignKey("aggregated_models.id"), index=True)
    public_model_name: Mapped[str] = mapped_column(String(128))
    model_type: Mapped[str] = mapped_column(String(32), index=True)
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True)
    node_id: Mapped[int | None] = mapped_column(ForeignKey("model_nodes.id"), nullable=True)
    route_priority: Mapped[int] = mapped_column(Integer, default=100)
    weight: Mapped[int] = mapped_column(Integer, default=100)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    max_requests_per_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_tokens_per_day: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class RequestLog(Base):
    __tablename__ = "request_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    api_key_masked: Mapped[str | None] = mapped_column(String(32), nullable=True)
    api_key_masked: Mapped[str | None] = mapped_column(String(32), nullable=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    api_key_id: Mapped[int | None] = mapped_column(ForeignKey("api_keys.id"), nullable=True)
    aggregate_model_id: Mapped[int | None] = mapped_column(
        ForeignKey("aggregated_models.id"), nullable=True
    )
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("providers.id"), nullable=True)
    provider_model_id: Mapped[int | None] = mapped_column(
        ForeignKey("provider_models.id"), nullable=True
    )
    node_id: Mapped[int | None] = mapped_column(ForeignKey("model_nodes.id"), nullable=True)
    public_model_name: Mapped[str] = mapped_column(String(128))
    model_type: Mapped[str] = mapped_column(String(32))
    endpoint: Mapped[str] = mapped_column(String(128))
    request_method: Mapped[str] = mapped_column(String(16), default="POST")
    requester_ip: Mapped[str] = mapped_column(String(64))
    request_body: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    response_body: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    http_status: Mapped[int] = mapped_column(Integer)
    provider_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ttft_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tpot_ms: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    request_log_id: Mapped[int] = mapped_column(ForeignKey("request_logs.id"), unique=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    api_key_id: Mapped[int | None] = mapped_column(ForeignKey("api_keys.id"), nullable=True)
    aggregate_model_id: Mapped[int | None] = mapped_column(
        ForeignKey("aggregated_models.id"), nullable=True
    )
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("providers.id"), nullable=True)
    provider_model_id: Mapped[int | None] = mapped_column(
        ForeignKey("provider_models.id"), nullable=True
    )
    node_id: Mapped[int | None] = mapped_column(ForeignKey("model_nodes.id"), nullable=True)
    model_type: Mapped[str] = mapped_column(String(32))
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    non_reasoning_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    currency: Mapped[str] = mapped_column(String(16), default="CNY")
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class PlaygroundRecord(Base):
    __tablename__ = "playground_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    mode: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(16))
    model_code: Mapped[str] = mapped_column(String(128))
    protocol: Mapped[str] = mapped_column(String(32))
    stream: Mapped[bool] = mapped_column(Boolean, default=False)
    request_url: Mapped[str] = mapped_column(Text)
    request_headers: Mapped[dict] = mapped_column(JSONB)
    request_body: Mapped[dict] = mapped_column(JSONB)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC), index=True)


class GatewayLogSettings(Base):
    __tablename__ = "gateway_log_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    image_mode: Mapped[str] = mapped_column(String(24), default="content_only")


class FeishuSettings(Base):
    __tablename__ = "feishu_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_id: Mapped[str] = mapped_column(String(128))
    app_secret_ciphertext: Mapped[str] = mapped_column(Text)
    chat_id: Mapped[str] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class AlertRule(TimestampMixin, Base):
    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    metric: Mapped[str] = mapped_column(String(32))
    scope_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    threshold: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    window_minutes: Mapped[int] = mapped_column(Integer, default=5)
    min_samples: Mapped[int] = mapped_column(Integer, default=10)
    level: Mapped[str] = mapped_column(String(16), default="warning")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    suppressed_until_recovery: Mapped[bool] = mapped_column(Boolean, default=False)
    recipients: Mapped[list] = mapped_column(JSONB, default=list)


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("alert_rules.id"), index=True)
    recipients: Mapped[list] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    current_value: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    threshold: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AlertDelivery(Base):
    __tablename__ = "alert_deliveries"
    __table_args__ = (UniqueConstraint(
        "event_id", "kind", "receive_id_type", "receive_id",
        name="uq_alert_delivery_target",
    ),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("alert_events.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    receive_id_type: Mapped[str] = mapped_column(String(16), default="chat_id")
    receive_id: Mapped[str] = mapped_column(String(128), default="")
    current_value: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
