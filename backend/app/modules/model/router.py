from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from time import perf_counter
from typing import Literal
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator
from redis.exceptions import RedisError
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.gateway.router import connection
from app.core.list_filters import filter_expression
from app.core.responses import success_response
from app.db.models import (
    AggregatedModel,
    Provider,
    ProviderModel,
    ProviderProtocol,
    ProviderSecret,
    RequestLog,
    RoutingWorkflow,
    UsageRecord,
    User,
)
from app.db.session import get_db
from app.modules.gateway.adapters import normalize, prepare
from app.modules.gateway.limits import cooldown_key, limiter
from app.modules.identity.router import actor, require_platform
from app.modules.routing.strategies import STRATEGIES, choose_model, validate_candidates
from app.modules.routing.workflow import Definition, SimulationOptions, simulate, validate_bindings

router = APIRouter(tags=["模型治理"])

ModelType = Literal["llm", "vlm", "embedding", "rerank", "asr", "tts", "ocr", "text_to_image"]
SUPPORTED_PROTOCOL_TYPES = {"openai", "openai_compatible", "gemini", "claude", "anthropic"}
AGGREGATE_NAME_PATTERN = re.compile(r"[A-Za-z0-9_.\-\u3400-\u9fff]+")


class PriceTier(BaseModel):
    model_config = ConfigDict(extra="forbid")

    up_to_tokens: int | None = Field(default=None, ge=1, le=2147483647)
    price: Decimal = Field(ge=0, lt=1000000000000)

    @field_validator("price")
    @classmethod
    def round_price(cls, value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def validate_tiers(enabled: bool, inputs: list[PriceTier], outputs: list[PriceTier]) -> None:
    for label, tiers in (("输入", inputs), ("输出", outputs)):
        if len(tiers) > 20:
            raise ValueError(f"{label}阶梯最多配置 20 档。")
        if enabled and not tiers:
            raise ValueError(f"开启阶梯定价时必须配置{label}阶梯。")
        previous = 0
        for index, tier in enumerate(tiers):
            if tier.up_to_tokens is None:
                if index != len(tiers) - 1:
                    raise ValueError(f"{label}阶梯的不限上限只能是最后一档。")
            elif tier.up_to_tokens <= previous:
                raise ValueError(f"{label}阶梯上限必须严格递增。")
            else:
                previous = tier.up_to_tokens
        if tiers and tiers[-1].up_to_tokens is not None:
            raise ValueError(f"{label}阶梯最后一档必须不设上限。")


class AccessModelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_id: int = Field(gt=0)
    protocol_id: int = Field(gt=0)
    secret_id: int | None = Field(default=None, gt=0)
    access_model_code: str = Field(min_length=1, max_length=128)
    provider_model_name: str = Field(min_length=1, max_length=128)
    model_type: ModelType
    base_url: HttpUrl | None = Field(default=None, max_length=255)
    region: str | None = Field(default=None, max_length=64)
    max_concurrency: int | None = Field(default=None, ge=1, le=100000)
    context_window: int | None = Field(default=None, ge=1, le=2147483647)
    timeout_ms: int | None = Field(default=None, ge=1, le=600000)
    price_unit_k: int = Field(default=1, ge=1, le=1000000)
    input_price: Decimal | None = Field(default=None, ge=0, lt=1000000000000)
    output_price: Decimal | None = Field(default=None, ge=0, lt=1000000000000)
    tiered_pricing: bool = False
    input_price_tiers: list[PriceTier] = Field(default_factory=list)
    output_price_tiers: list[PriceTier] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_prices(self) -> AccessModelCreate:
        if (self.input_price is None) != (self.output_price is None):
            raise ValueError("输入和输出单价必须同时配置。")
        validate_tiers(self.tiered_pricing, self.input_price_tiers, self.output_price_tiers)
        return self

    @field_validator("input_price", "output_price")
    @classmethod
    def round_price(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @field_validator("base_url", mode="before")
    @classmethod
    def empty_url_inherits_provider(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value


class AccessModelUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol_id: int | None = Field(default=None, gt=0)
    secret_id: int | None = Field(default=None, gt=0)
    provider_model_name: str | None = Field(default=None, min_length=1, max_length=128)
    model_type: ModelType | None = None
    base_url: HttpUrl | None = Field(default=None, max_length=255)
    region: str | None = Field(default=None, max_length=64)
    max_concurrency: int | None = Field(default=None, ge=1, le=100000)
    context_window: int | None = Field(default=None, ge=1, le=2147483647)
    timeout_ms: int | None = Field(default=None, ge=1, le=600000)
    price_unit_k: int | None = Field(default=None, ge=1, le=1000000)
    input_price: Decimal | None = Field(default=None, ge=0, lt=1000000000000)
    output_price: Decimal | None = Field(default=None, ge=0, lt=1000000000000)
    tiered_pricing: bool | None = None
    input_price_tiers: list[PriceTier] | None = None
    output_price_tiers: list[PriceTier] | None = None
    status: Literal[0, 1] | None = None

    @field_validator("input_price", "output_price")
    @classmethod
    def round_price(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @field_validator("base_url", mode="before")
    @classmethod
    def empty_url_inherits_provider(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value


def serialize(item: ProviderModel, provider_base_url: str | None) -> dict:
    return {
        "id": item.id, "provider_id": item.provider_id, "protocol_id": item.protocol_id,
        "secret_id": item.secret_id, "access_model_code": item.access_model_code,
        "provider_model_name": item.provider_model_name, "model_type": item.model_type,
        "base_url": item.base_url, "effective_base_url": item.base_url or provider_base_url,
        "region": item.region,
        "max_concurrency": item.max_concurrency, "context_window": item.context_window,
        "timeout_ms": item.timeout_ms,
        "status": item.status, "currency": item.currency,
        "price_unit_k": item.price_unit_k, "input_price": item.input_price,
        "output_price": item.output_price,
        "tiered_pricing": item.tiered_pricing,
        "input_price_tiers": item.input_price_tiers or [],
        "output_price_tiers": item.output_price_tiers or [],
    }


def validate_refs(db: Session, provider_id: int, protocol_id: int, secret_id: int | None) -> None:
    if db.get(Provider, provider_id) is None:
        raise HTTPException(404, "供应商不存在。")
    protocol = db.get(ProviderProtocol, protocol_id)
    if protocol is None or protocol.provider_id != provider_id or protocol.status != 1:
        raise HTTPException(422, "协议必须是该供应商的已启用配置。")
    if protocol.protocol_type not in SUPPORTED_PROTOCOL_TYPES:
        raise HTTPException(422, "接入模型仅支持 OpenAI、Gemini 和 Claude 接口协议。")
    if secret_id is not None:
        secret = db.get(ProviderSecret, secret_id)
        if secret is None or secret.provider_id != provider_id or secret.status != 1:
            raise HTTPException(422, "密钥必须是该供应商的已启用配置。")


@router.get("/access-models")
def list_access_models(
    provider_id: int | None = None, page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    filters: str | None = Query(None, max_length=4096),
    db: Session = Depends(get_db), _user: User = Depends(actor),
) -> dict:
    statement = select(ProviderModel)
    if provider_id is not None:
        statement = statement.where(ProviderModel.provider_id == provider_id)
    if filters:
        provider_name = select(Provider.name).where(
            Provider.id == ProviderModel.provider_id).correlate(ProviderModel).scalar_subquery()
        provider_url = select(Provider.base_url).where(
            Provider.id == ProviderModel.provider_id).correlate(ProviderModel).scalar_subquery()
        expression = filter_expression(filters, {
            "id": (ProviderModel.id, "number"),
            "access_model_code": (ProviderModel.access_model_code, "text"),
            "provider_model_name": (ProviderModel.provider_model_name, "text"),
            "provider_name": (provider_name, "text"),
            "model_type": (ProviderModel.model_type, "text"),
            "protocol_id": (ProviderModel.protocol_id, "number"),
            "secret_id": (ProviderModel.secret_id, "number"),
            "effective_base_url": (func.coalesce(ProviderModel.base_url, provider_url), "text"),
            "region": (ProviderModel.region, "text"),
            "max_concurrency": (ProviderModel.max_concurrency, "number"),
            "context_window": (ProviderModel.context_window, "number"),
            "timeout_ms": (ProviderModel.timeout_ms, "number"),
            "input_price": (ProviderModel.input_price, "decimal"),
            "output_price": (ProviderModel.output_price, "decimal"),
            "tiered_pricing": (ProviderModel.tiered_pricing, "boolean", {"0", "1"}),
            "status": (ProviderModel.status, "select", {"0", "1"}),
        })
        if expression is not None:
            statement = statement.where(expression)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    items = db.scalars(statement.order_by(ProviderModel.id.desc()).offset(
        (page - 1) * page_size).limit(page_size)).all()
    provider_urls = dict(db.execute(
        select(Provider.id, Provider.base_url).where(
            Provider.id.in_({item.provider_id for item in items}))
    ).all())
    return success_response({
        "items": [serialize(item, provider_urls.get(item.provider_id)) for item in items], "page": page,
        "page_size": page_size, "total": total,
    }).model_dump()


@router.post("/access-models", status_code=201)
def create_access_model(
    payload: AccessModelCreate, db: Session = Depends(get_db), user: User = Depends(actor),
) -> dict:
    require_platform(user)
    validate_refs(db, payload.provider_id, payload.protocol_id, payload.secret_id)
    data = payload.model_dump()
    for field in ("input_price_tiers", "output_price_tiers"):
        data[field] = [tier.model_dump(mode="json") for tier in getattr(payload, field)]
    data["base_url"] = str(payload.base_url) if payload.base_url else None
    data["region"] = (payload.region.strip() or None) if payload.region is not None else None
    for field in ("access_model_code", "provider_model_name", "model_type"):
        data[field] = data[field].strip()
        if not data[field]:
            raise HTTPException(422, f"{field} 不能为空。")
    if db.scalar(select(ProviderModel.id).where(
        ProviderModel.access_model_code == data["access_model_code"])) is not None:
        raise HTTPException(409, "接入模型编码已存在。")
    item = ProviderModel(**data, status=1, currency="CNY")
    return save(db, item)


@router.get("/access-models/{model_id}")
def access_model_detail(
    model_id: int, db: Session = Depends(get_db), _user: User = Depends(actor),
) -> dict:
    item = db.get(ProviderModel, model_id)
    if item is None:
        raise HTTPException(404, "接入模型不存在。")
    provider = db.get(Provider, item.provider_id)
    return success_response(serialize(item, provider.base_url if provider else None)).model_dump()


@router.patch("/access-models/{model_id}")
def update_access_model(
    model_id: int, payload: AccessModelUpdate,
    db: Session = Depends(get_db), user: User = Depends(actor),
) -> dict:
    require_platform(user)
    item = db.get(ProviderModel, model_id)
    if item is None:
        raise HTTPException(404, "接入模型不存在。")
    changes = payload.model_dump(exclude_unset=True)
    if any(field in changes for field in (
        "tiered_pricing", "input_price_tiers", "output_price_tiers",
    )):
        if changes.get("tiered_pricing", item.tiered_pricing) is None:
            raise HTTPException(422, "阶梯定价开关不能为空。")
        if any(field in changes and changes[field] is None
               for field in ("input_price_tiers", "output_price_tiers")):
            raise HTTPException(422, "阶梯配置不能为 null。")
        try:
            validate_tiers(
                changes.get("tiered_pricing", item.tiered_pricing),
                [PriceTier.model_validate(tier) for tier in changes.get(
                    "input_price_tiers", item.input_price_tiers or [],
                )],
                [PriceTier.model_validate(tier) for tier in changes.get(
                    "output_price_tiers", item.output_price_tiers or [],
                )],
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        for field in ("input_price_tiers", "output_price_tiers"):
            if field in changes:
                changes[field] = [
                    PriceTier.model_validate(tier).model_dump(mode="json")
                    for tier in changes[field]
                ]
        if changes.get("tiered_pricing", item.tiered_pricing):
            changes["currency"] = "CNY"
            if item.currency != "CNY":
                changes.setdefault("input_price", None)
                changes.setdefault("output_price", None)
    if changes.get("price_unit_k") is None and "price_unit_k" in changes:
        raise HTTPException(422, "计价单位不能为空。")
    if "input_price" in changes or "output_price" in changes:
        changes["currency"] = "CNY"
        # Do not silently reinterpret the other side of a legacy USD price.
        if item.currency != "CNY":
            if "input_price" not in changes:
                changes["input_price"] = None
            if "output_price" not in changes:
                changes["output_price"] = None
        if (changes.get("input_price", item.input_price) is None) != (
            changes.get("output_price", item.output_price) is None
        ):
            raise HTTPException(422, "输入和输出单价必须同时配置。")
    if "protocol_id" in changes and changes["protocol_id"] is None:
        raise HTTPException(422, "协议不能为空。")
    if "base_url" in changes:
        changes["base_url"] = str(changes["base_url"]) if changes["base_url"] else None
    if "region" in changes and changes["region"] is not None:
        changes["region"] = changes["region"].strip() or None
    for field in ("provider_model_name", "model_type"):
        if field in changes:
            if changes[field] is None or not changes[field].strip():
                raise HTTPException(422, f"{field} 不能为空。")
            changes[field] = changes[field].strip()
    if "status" in changes and changes["status"] is None:
        raise HTTPException(422, "状态不能为空。")
    if "model_type" in changes and changes["model_type"] != item.model_type:
        for workflow in db.scalars(select(RoutingWorkflow)).all():
            if any(
                node.get("config", {}).get("model_id") == item.id
                or any(candidate.get("model_id") == item.id for candidate in node.get("config", {}).get("candidates", []))
                for node in workflow.definition.get("nodes", [])
            ):
                raise HTTPException(409, "接入模型已被路由流程引用，不能修改模型类型。")
        if any(
            item.id in candidates
            for aggregate in db.scalars(select(AggregatedModel).where(
                AggregatedModel.workflow_id.is_not(None),
            )).all()
            for candidates in (aggregate.workflow_bindings or {}).values()
        ):
            raise HTTPException(409, "接入模型已被聚合模型的流程槽位引用，不能修改模型类型。")
        if any(
            item.id in (aggregate.routing_model_ids or [])
            for aggregate in db.scalars(select(AggregatedModel).where(
                AggregatedModel.routing_model_ids.is_not(None),
            )).all()
        ):
            raise HTTPException(409, "接入模型已被聚合模型候选列表引用，不能修改模型类型。")
        if db.scalar(select(AggregatedModel.id).where(
            AggregatedModel.fallback_model_id == item.id,
        )) is not None:
            raise HTTPException(409, "接入模型已被设为兜底模型，不能修改模型类型。")
    if "protocol_id" in changes or "secret_id" in changes or changes.get("status") == 1:
        validate_refs(db, item.provider_id, changes.get("protocol_id", item.protocol_id),
                      changes.get("secret_id", item.secret_id))
    for field, value in changes.items():
        setattr(item, field, value)
    return save(db, item)


def save(db: Session, item: ProviderModel) -> dict:
    try:
        db.add(item)
        db.commit()
        db.refresh(item)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "模型配置与现有数据冲突。") from exc
    provider = db.get(Provider, item.provider_id)
    return success_response(serialize(item, provider.base_url if provider else None)).model_dump()


@router.get("/aggregate-models")
def list_aggregate_models(
    page: int = Query(1, ge=1), page_size: int | None = Query(None, ge=1, le=100),
    keyword: str = Query("", max_length=128),
    filters: str | None = Query(None, max_length=4096),
    db: Session = Depends(get_db), _user: User = Depends(actor),
) -> dict:
    statement = select(AggregatedModel)
    if keyword.strip():
        pattern = f"%{keyword.strip()}%"
        statement = statement.where(
            AggregatedModel.public_model_name.ilike(pattern)
            | AggregatedModel.aggregate_model_code.ilike(pattern)
        )
    if filters:
        expression = filter_expression(filters, {
            "id": (AggregatedModel.id, "number"),
            "public_model_name": (AggregatedModel.public_model_name, "text"),
            "aggregate_model_code": (AggregatedModel.aggregate_model_code, "text"),
            "model_type": (AggregatedModel.model_type, "text"),
            "default_routing_strategy": (AggregatedModel.default_routing_strategy, "text"),
            "fallback_model_id": (AggregatedModel.fallback_model_id, "number"),
            "status": (AggregatedModel.status, "select", {"0", "1"}),
        })
        if expression is not None:
            statement = statement.where(expression)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    statement = statement.order_by(AggregatedModel.id)
    if page_size is not None:
        statement = statement.offset((page - 1) * page_size).limit(page_size)
    items = db.scalars(statement).all()
    return success_response({
        "items": [{
            "id": item.id, "aggregate_model_code": item.aggregate_model_code,
            "public_model_name": item.public_model_name, "model_type": item.model_type,
            "default_routing_strategy": item.default_routing_strategy, "status": item.status,
            "routing_model_ids": item.routing_model_ids or [],
            "fallback_model_id": item.fallback_model_id,
            "retry_on_failure": item.retry_on_failure,
            "description": item.description, "workflow_id": item.workflow_id,
            "workflow_bindings": item.workflow_bindings or {},
        } for item in items],
        "page": page, "page_size": page_size if page_size is not None else len(items), "total": total,
    }).model_dump()


@router.get("/aggregate-models/{aggregate_id}/nodes")
async def aggregate_nodes(
    aggregate_id: int, db: Session = Depends(get_db), _user: User = Depends(actor),
) -> dict:
    aggregate = db.get(AggregatedModel, aggregate_id)
    if aggregate is None:
        raise HTTPException(404, "聚合模型不存在。")
    candidate_ids = aggregate.routing_model_ids or []
    ids = list(dict.fromkeys(candidate_ids + (
        [aggregate.fallback_model_id] if aggregate.fallback_model_id else []
    )))
    if not ids:
        return success_response({"nodes": [], "window_hours": 24}).model_dump()
    models = {model.id: model for model in db.scalars(
        select(ProviderModel).where(ProviderModel.id.in_(ids))
    )}
    speed = case((
        (RequestLog.ttft_ms.is_not(None))
        & (RequestLog.latency_ms > RequestLog.ttft_ms)
        & (UsageRecord.output_tokens > 0),
        1000.0 * UsageRecord.output_tokens / (RequestLog.latency_ms - RequestLog.ttft_ms),
    ), else_=None)
    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=24)
    rows = db.execute(select(
        RequestLog.provider_model_id,
        func.count(RequestLog.ttft_ms), func.avg(RequestLog.ttft_ms),
        func.count(speed), func.avg(speed),
    ).select_from(RequestLog).outerjoin(
        UsageRecord, UsageRecord.request_log_id == RequestLog.id,
    ).where(
        RequestLog.aggregate_model_id == aggregate_id,
        RequestLog.provider_model_id.in_(ids),
        RequestLog.created_at >= since,
        RequestLog.http_status.between(200, 299),
    ).group_by(RequestLog.provider_model_id)).all()
    metrics = {model_id: (ttft_count, ttft, speed_count, tps)
               for model_id, ttft_count, ttft, speed_count, tps in rows}
    cooldowns = {}
    if aggregate.retry_on_failure:
        service = limiter()
        try:
            async with service.client.pipeline() as pipe:
                for model_id in ids:
                    pipe.ttl(cooldown_key(model_id))
                cooldowns = dict(zip(ids, await pipe.execute(), strict=True))
        except RedisError as exc:
            raise HTTPException(503, "节点退避状态暂不可用。") from exc
        finally:
            await service.client.aclose()
    nodes = []
    for model_id in ids:
        model = models.get(model_id)
        ttft_count, ttft, speed_count, tps = metrics.get(model_id, (0, None, 0, None))
        cooldown = max(0, cooldowns.get(model_id, 0))
        status = ("missing" if model is None else "disabled" if model.status != 1
                  else "cooldown" if cooldown else "available")
        nodes.append({
            "model_id": model_id,
            "access_model_code": model.access_model_code if model else f"#{model_id}",
            "role": ("candidate_and_fallback" if model_id in candidate_ids
                     and model_id == aggregate.fallback_model_id else
                     "candidate" if model_id in candidate_ids else "fallback"),
            "status": status, "cooldown_seconds": cooldown,
            "ttft_samples": int(ttft_count),
            "avg_ttft_ms": round(float(ttft), 2) if ttft is not None else None,
            "tps_samples": int(speed_count),
            "avg_tps": round(float(tps), 2) if tps is not None else None,
        })
    return success_response({"nodes": nodes, "window_hours": 24}).model_dump()


class AggregateProbeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_ids: list[int] = Field(min_length=1, max_length=31)
    mode: Literal["network", "actual"]

    @field_validator("model_ids")
    @classmethod
    def unique_model_ids(cls, value: list[int]) -> list[int]:
        if any(model_id <= 0 for model_id in value) or len(value) != len(set(value)):
            raise ValueError("请选择不重复的有效节点。")
        return value


def probe_payload(model: ProviderModel) -> tuple[str, dict] | None:
    name = model.provider_model_name
    if model.model_type in ("llm", "vlm"):
        return "chat", {"model": name, "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 1, "stream": False}
    if model.model_type == "embedding":
        return "embedding", {"model": name, "input": "ping"}
    if model.model_type == "rerank":
        return "rerank", {"model": name, "query": "ping", "documents": ["ping"], "top_n": 1}
    if model.model_type == "text_to_image":
        return "image", {
            "model": name, "prompt": "A plain blue square", "size": "1024x1024", "n": 1,
        }
    return None


async def probe_node(db: Session, model: ProviderModel, mode: str) -> dict:
    started = perf_counter()

    def result(status: str, message: str, http_status: int | None = None) -> dict:
        return {"model_id": model.id, "result": status, "message": message,
                "latency_ms": round((perf_counter() - started) * 1000),
                "http_status": http_status}

    if model.status != 1:
        return result("failed", "接入模型已停用。")
    try:
        if mode == "network":
            provider = db.get(Provider, model.provider_id)
            protocol = db.get(ProviderProtocol, model.protocol_id) if model.protocol_id else None
            if provider is None or provider.status != 1 or protocol is None \
                    or protocol.status != 1 or protocol.provider_id != model.provider_id:
                return result("failed", "供应商或协议配置不可用。")
            base = model.base_url or protocol.base_url or provider.base_url
            target = urlsplit(base)
            if target.scheme not in ("http", "https") or not target.hostname:
                return result("failed", "连接地址配置无效。")
            port = target.port or (443 if target.scheme == "https" else 80)
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(target.hostname, port, ssl=target.scheme == "https"),
                timeout=5,
            )
            writer.close()
            await asyncio.wait_for(writer.wait_closed(), timeout=2)
            return result("ok", "TCP/TLS 连通；未验证模型或鉴权。")

        payload = probe_payload(model)
        if payload is None:
            return result("unsupported", "该模型类型暂无通用的最小调用格式，请使用网络检测。")
        kind, body = payload
        protocol, base, secret, _ = connection(db, model)
        url, headers, upstream_body = prepare(
            protocol, base, model.provider_model_name, secret, body, kind,
        )
        async with asyncio.timeout(10):
            async with httpx.AsyncClient(timeout=8.0, trust_env=False) as client:
                async with client.stream(
                    "POST", url, headers=headers, json=upstream_body,
                ) as response:
                    if response.status_code >= 400 or response.is_redirect:
                        return result(
                            "failed", f"上游返回 HTTP {response.status_code}。",
                            response.status_code,
                        )
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > 8 * 1024 * 1024:
                            return result("failed", "上游响应过大。", response.status_code)
        response_body = json.loads(content)
        normalized = normalize(response_body, protocol, kind, model.access_model_code)
        field = "choices" if kind == "chat" else "results" if kind == "rerank" else "data"
        if not normalized.get(field):
            return result("failed", "上游响应缺少有效结果。", response.status_code)
        return result("ok", "模型调用成功。", response.status_code)
    except HTTPException:
        return result("failed", "模型连接配置或协议不可用。")
    except (asyncio.TimeoutError, httpx.TimeoutException):
        return result("failed", "检测超时。")
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError,
            httpx.RequestError):
        return result("failed", "连接失败或上游响应格式异常。")


@router.post("/aggregate-models/{aggregate_id}/nodes/probe")
async def probe_aggregate_nodes(
    aggregate_id: int, payload: AggregateProbeRequest,
    db: Session = Depends(get_db), _user: User = Depends(actor),
) -> dict:
    require_platform(_user)
    aggregate = db.get(AggregatedModel, aggregate_id)
    if aggregate is None:
        raise HTTPException(404, "聚合模型不存在。")
    allowed = set(aggregate.routing_model_ids or [])
    if aggregate.fallback_model_id:
        allowed.add(aggregate.fallback_model_id)
    if not set(payload.model_ids) <= allowed:
        raise HTTPException(422, "只能检测当前聚合模型配置的节点。")
    models = {model.id: model for model in db.scalars(
        select(ProviderModel).where(ProviderModel.id.in_(payload.model_ids))
    )}
    if any(model_id not in models or models[model_id].model_type != aggregate.model_type
           for model_id in payload.model_ids):
        raise HTTPException(422, "节点不存在或模型类型不匹配。")
    semaphore = asyncio.Semaphore(4)

    async def check(model_id: int) -> dict:
        async with semaphore:
            return await probe_node(db, models[model_id], payload.mode)

    results = await asyncio.gather(*(check(model_id) for model_id in payload.model_ids))
    return success_response({"results": results}).model_dump()


class AggregatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    aggregate_model_code: str = Field(min_length=1, max_length=128)
    public_model_name: str = Field(min_length=1, max_length=128)
    model_type: ModelType
    description: str | None = Field(default=None, max_length=255)
    default_routing_strategy: Literal["single", "round_robin", "least_latency"] = "single"
    routing_model_ids: list[int] = Field(default_factory=list)
    fallback_model_id: int | None = Field(default=None, gt=0)
    retry_on_failure: bool = False
    status: Literal[0, 1] = 0


def aggregate_dict(item: AggregatedModel) -> dict:
    return {
        "id": item.id, "aggregate_model_code": item.aggregate_model_code,
        "public_model_name": item.public_model_name, "model_type": item.model_type,
        "description": item.description, "workflow_id": item.workflow_id,
        "workflow_bindings": item.workflow_bindings or {},
        "routing_model_ids": item.routing_model_ids or [],
        "fallback_model_id": item.fallback_model_id,
        "retry_on_failure": item.retry_on_failure,
        "status": item.status, "default_routing_strategy": item.default_routing_strategy,
    }


def check_aggregate(db: Session, payload: AggregatePayload, exclude_id: int | None = None) -> None:
    if not AGGREGATE_NAME_PATTERN.fullmatch(payload.aggregate_model_code):
        raise HTTPException(422, "聚合编码只能包含中英文、数字、下划线、连字符和小数点。")
    if not AGGREGATE_NAME_PATTERN.fullmatch(payload.public_model_name):
        raise HTTPException(422, "对外模型名称只能包含中英文、数字、下划线、连字符和小数点。")
    models = validate_candidates(
        db, payload.default_routing_strategy, payload.routing_model_ids, payload.model_type,
    )
    if payload.retry_on_failure and payload.default_routing_strategy == "single":
        raise HTTPException(422, "失败切换仅支持轮询和最低延迟策略。")
    fallback = db.get(ProviderModel, payload.fallback_model_id) if payload.fallback_model_id else None
    if payload.fallback_model_id and (fallback is None or fallback.model_type != payload.model_type):
        raise HTTPException(422, "兜底模型不存在或与聚合模型类型不一致。")
    if payload.status == 1 and not (
        any(model.status == 1 for model in models.values()) or (fallback is not None and fallback.status == 1)
    ):
        raise HTTPException(422, "启用前至少需要一个可用的接入模型。")
    existing = db.scalar(select(AggregatedModel.id).where(
        AggregatedModel.public_model_name == payload.public_model_name.strip(),
        AggregatedModel.id != exclude_id,
    ))
    if existing is not None:
        raise HTTPException(409, "对外模型名称已存在，避免网关请求歧义。")
    existing = db.scalar(select(AggregatedModel.id).where(
        AggregatedModel.aggregate_model_code == payload.aggregate_model_code,
        AggregatedModel.id != exclude_id,
    ))
    if existing is not None:
        raise HTTPException(409, "聚合模型编码已存在。")


def save_aggregate(db: Session, item: AggregatedModel) -> dict:
    try:
        db.add(item)
        db.commit()
        db.refresh(item)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "聚合模型配置冲突。") from exc
    return success_response(aggregate_dict(item)).model_dump()


@router.post("/aggregate-models", status_code=201)
def create_aggregate(
    payload: AggregatePayload, db: Session = Depends(get_db), user: User = Depends(actor),
) -> dict:
    require_platform(user)
    check_aggregate(db, payload)
    item = AggregatedModel(
        **payload.model_dump(exclude={"description", "public_model_name"}),
        public_model_name=payload.public_model_name.strip(),
        description=payload.description,
    )
    return save_aggregate(db, item)


@router.put("/aggregate-models/{aggregate_id}")
def update_aggregate(
    aggregate_id: int, payload: AggregatePayload,
    db: Session = Depends(get_db), user: User = Depends(actor),
) -> dict:
    require_platform(user)
    item = db.get(AggregatedModel, aggregate_id)
    if item is None:
        raise HTTPException(404, "聚合模型不存在。")
    check_aggregate(db, payload, aggregate_id)
    for field, value in payload.model_dump().items():
        setattr(item, field, value.strip() if field == "public_model_name" else value)
    item.workflow_id = None
    item.workflow_bindings = None
    return save_aggregate(db, item)


@router.post("/aggregate-models/{aggregate_id}/simulate")
def simulate_aggregate(
    aggregate_id: int, payload: SimulationOptions,
    db: Session = Depends(get_db), _user: User = Depends(actor),
) -> dict:
    item = db.get(AggregatedModel, aggregate_id)
    if item is None:
        raise HTTPException(404, "聚合模型不存在。")
    if item.default_routing_strategy in STRATEGIES:
        models = validate_candidates(
            db, item.default_routing_strategy, item.routing_model_ids or [], item.model_type,
        )
        if item.fallback_model_id is not None:
            fallback = db.get(ProviderModel, item.fallback_model_id)
            if fallback is None or fallback.model_type != item.model_type:
                raise HTTPException(422, "兜底模型不存在或与聚合模型类型不一致。")
            models[fallback.id] = fallback
        if any(value < 0 for value in payload.latencies.values()):
            raise HTTPException(422, "延迟毫秒数不能为负数。")
        return success_response(choose_model(
            item.default_routing_strategy, item.routing_model_ids or [], models,
            round_robin_index=payload.round_robin_index, latencies=payload.latencies,
            fallback_model_id=item.fallback_model_id,
        )).model_dump()
    if item.workflow_id is None:
        raise HTTPException(422, "该聚合模型尚未配置可用路由策略。")
    workflow = db.get(RoutingWorkflow, item.workflow_id)
    if workflow is None:
        raise HTTPException(404, "路由流程不存在。")
    definition = Definition.model_validate(workflow.definition)
    bindings = item.workflow_bindings or {}
    models = validate_bindings(db, definition, bindings, item.model_type)
    if any(value < 0 for value in payload.latencies.values()):
        raise HTTPException(422, "延迟毫秒数不能为负数。")
    return success_response(simulate(
        definition, models, bindings=bindings, latencies=payload.latencies,
        round_robin_index=payload.round_robin_index, region=payload.region, stream=payload.stream,
        seed=payload.seed,
    )).model_dump()
