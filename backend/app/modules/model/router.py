from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.responses import success_response
from app.db.models import AggregatedModel, Provider, ProviderModel, ProviderProtocol, ProviderSecret, RoutingWorkflow, User
from app.db.session import get_db
from app.modules.identity.router import actor, require_platform
from app.modules.routing.strategies import STRATEGIES, choose_model, validate_candidates
from app.modules.routing.workflow import Definition, SimulationOptions, simulate, validate_bindings

router = APIRouter(tags=["模型治理"])

ModelType = Literal["llm", "vlm", "embedding", "rerank", "asr", "tts", "ocr", "text_to_image"]
SUPPORTED_PROTOCOL_TYPES = {"openai", "openai_compatible", "gemini", "claude", "anthropic"}
AGGREGATE_NAME_PATTERN = re.compile(r"[A-Za-z0-9_.\-\u3400-\u9fff]+")


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
    status: Literal[0, 1] | None = None

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
    db: Session = Depends(get_db), _user: User = Depends(actor),
) -> dict:
    statement = select(ProviderModel)
    if provider_id is not None:
        statement = statement.where(ProviderModel.provider_id == provider_id)
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
    data["base_url"] = str(payload.base_url) if payload.base_url else None
    data["region"] = (payload.region.strip() or None) if payload.region is not None else None
    for field in ("access_model_code", "provider_model_name", "model_type"):
        data[field] = data[field].strip()
        if not data[field]:
            raise HTTPException(422, f"{field} 不能为空。")
    if db.scalar(select(ProviderModel.id).where(
        ProviderModel.access_model_code == data["access_model_code"])) is not None:
        raise HTTPException(409, "接入模型编码已存在。")
    item = ProviderModel(**data, status=1, currency="USD")
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
    db: Session = Depends(get_db), _user: User = Depends(actor),
) -> dict:
    items = db.scalars(select(AggregatedModel).order_by(AggregatedModel.id)).all()
    return success_response({
        "items": [{
            "id": item.id, "aggregate_model_code": item.aggregate_model_code,
            "public_model_name": item.public_model_name, "model_type": item.model_type,
            "default_routing_strategy": item.default_routing_strategy, "status": item.status,
            "routing_model_ids": item.routing_model_ids or [],
            "fallback_model_id": item.fallback_model_id,
            "description": item.description, "workflow_id": item.workflow_id,
            "workflow_bindings": item.workflow_bindings or {},
        } for item in items],
        "page": 1, "page_size": len(items), "total": len(items),
    }).model_dump()


class AggregatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    aggregate_model_code: str = Field(min_length=1, max_length=128)
    public_model_name: str = Field(min_length=1, max_length=128)
    model_type: ModelType
    description: str | None = Field(default=None, max_length=255)
    default_routing_strategy: Literal["single", "round_robin", "least_latency"] = "single"
    routing_model_ids: list[int] = Field(default_factory=list)
    fallback_model_id: int | None = Field(default=None, gt=0)
    status: Literal[0, 1] = 0


def aggregate_dict(item: AggregatedModel) -> dict:
    return {
        "id": item.id, "aggregate_model_code": item.aggregate_model_code,
        "public_model_name": item.public_model_name, "model_type": item.model_type,
        "description": item.description, "workflow_id": item.workflow_id,
        "workflow_bindings": item.workflow_bindings or {},
        "routing_model_ids": item.routing_model_ids or [],
        "fallback_model_id": item.fallback_model_id,
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
