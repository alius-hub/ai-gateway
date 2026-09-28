from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class OverviewSummary(BaseModel):
    total_requests: int = 0
    total_tokens: int = 0
    total_cost: Decimal = Field(default=Decimal("0"))
    organization_count: int = 0
    project_count: int = 0
    key_count: int = 0
    provider_count: int = 0
    model_count: int = 0
    node_count: int = 0
    active_node_count: int = 0
    healthy_provider_count: int = 0
    data_source: Literal["database", "bootstrap"] = "bootstrap"
    database_status: Literal["connected", "unavailable"] = "unavailable"
    status_message: str = "数据库尚未初始化，当前返回空汇总。"
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class OverviewDay(BaseModel):
    date: str
    requests: int = 0
    successes: int = 0
    tokens: int = 0


class OverviewModel(BaseModel):
    name: str
    requests: int


class OverviewFailure(BaseModel):
    request_id: str
    model: str
    http_status: int
    created_at: datetime


class OverviewActivity(BaseModel):
    days: int
    total_requests: int = 0
    successful_requests: int = 0
    total_tokens: int = 0
    daily: list[OverviewDay] = Field(default_factory=list)
    top_models: list[OverviewModel] = Field(default_factory=list)
    recent_failures: list[OverviewFailure] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
