from typing import Any

from pydantic import BaseModel, Field


class PaginationQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    keyword: str | None = None
    status: int | None = None


class PageData(BaseModel):
    items: list[Any] = Field(default_factory=list)
    page: int = 1
    page_size: int = 20
    total: int = 0


class HealthCheckResponse(BaseModel):
    status: str = "ok"
    service: str = "ai-gateway-backend"
