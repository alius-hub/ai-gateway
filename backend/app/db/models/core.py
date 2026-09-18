from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, Numeric, String, Text
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
    status: Mapped[int] = mapped_column(Integer, default=1)
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)


class Organization(TimestampMixin, Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[int] = mapped_column(Integer, default=1)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    code: Mapped[str] = mapped_column(String(64), index=True)
    environment: Mapped[str] = mapped_column(String(32), default="dev")
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[int] = mapped_column(Integer, default=1)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)


class ApiKey(TimestampMixin, Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    scope_type: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(128))
    key_prefix: Mapped[str] = mapped_column(String(32))
    key_hash: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    status: Mapped[int] = mapped_column(Integer, default=1)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    allowed_ips: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    allowed_models: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
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


class ProviderModel(TimestampMixin, Base):
    __tablename__ = "provider_models"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), index=True)
    access_model_code: Mapped[str] = mapped_column(String(128), index=True)
    provider_model_name: Mapped[str] = mapped_column(String(128))
    model_type: Mapped[str] = mapped_column(String(32), index=True)
    context_window: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    output_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    currency: Mapped[str] = mapped_column(String(16), default="USD")
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
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
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
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    request_log_id: Mapped[int] = mapped_column(ForeignKey("request_logs.id"), unique=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
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
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    currency: Mapped[str] = mapped_column(String(16), default="USD")
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
