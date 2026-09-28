from __future__ import annotations

# ruff: noqa: B008
import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.list_filters import filter_expression
from app.core.responses import success_response
from app.db.models import (
    AggregatedModel,
    ApiKey,
    Organization,
    Project,
    ProjectMember,
    ProviderModel,
    User,
)
from app.db.session import get_db
from app.modules.identity.router import actor, require_platform
from app.modules.routing.strategies import STRATEGIES

router = APIRouter(prefix="/credentials", tags=["凭证管理"])
DEFAULT_KEY_PREFIX = "agw_"
CUSTOM_PREFIX_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{1,19}\Z")


def normalize_prefix(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if not CUSTOM_PREFIX_PATTERN.fullmatch(value):
        raise ValueError("自定义前缀须为 2-20 位，以字母开头，仅含字母、数字、_ 或 -。")
    return value


class KeySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    aggregate_model_ids: list[int] = Field(default_factory=list)
    access_model_ids: list[int] = Field(default_factory=list)
    expires_at: datetime | None = None
    tpm_limit: int | None = Field(default=None, ge=1)
    qps_limit: int | None = Field(default=None, ge=1)
    token_budget: int | None = Field(default=None, ge=1)
    amount_budget: Decimal | None = Field(default=None, gt=0, lt=10000000000000000)
    budget_period: Literal["week", "month"] | None = None
    wait_mode: Literal["queue", "block"] = "block"
    max_wait_ms: int = Field(default=30000, ge=1000, le=300000)

    @field_validator("amount_budget")
    @classmethod
    def round_budget(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if rounded <= 0:
            raise ValueError("金额上限至少为 0.01 元。")
        return rounded

    @model_validator(mode="after")
    def validate_settings(self) -> KeySettings:
        if not self.name.strip():
            raise ValueError("Key 名称不能为空。")
        if not self.aggregate_model_ids and not self.access_model_ids:
            raise ValueError("至少绑定一个聚合模型或接入模型。")
        if ((self.token_budget is not None or self.amount_budget is not None)
                != (self.budget_period is not None)):
            raise ValueError("用量上限与统计周期必须同时配置。")
        if self.expires_at is not None:
            if not future(self.expires_at):
                raise ValueError("过期时间必须晚于当前时间。")
        return self


class CreateKey(KeySettings):
    user_id: int | None = Field(default=None, gt=0)
    project_id: int | None = Field(default=None, gt=0)
    organization_id: int | None = Field(default=None, gt=0)
    custom_prefix: str | None = Field(default=None, max_length=20)

    @field_validator("custom_prefix")
    @classmethod
    def validate_prefix(cls, value: str | None) -> str | None:
        return normalize_prefix(value)


class RotateKey(BaseModel):
    custom_prefix: str | None = Field(default=None, max_length=20)

    @field_validator("custom_prefix")
    @classmethod
    def validate_prefix(cls, value: str | None) -> str | None:
        return normalize_prefix(value)


class StatusPayload(BaseModel):
    status: Literal[0, 1]


def require_key(db: Session, key_id: int, scope: str) -> ApiKey:
    item = db.get(ApiKey, key_id)
    if item is None or item.scope_type != scope or item.deleted_at is not None:
        raise HTTPException(404, "Key 不存在。")
    return item


def future(expiry: datetime) -> bool:
    normalized = expiry.replace(tzinfo=UTC) if expiry.tzinfo is None else expiry
    return normalized > datetime.now(UTC)


def serialize(item: ApiKey) -> dict:
    grants = item.allowed_models if isinstance(item.allowed_models, dict) else {}
    return {
        "id": item.id, "scope_type": item.scope_type, "name": item.name,
        "organization_id": item.organization_id, "project_id": item.project_id,
        "user_id": item.user_id, "key_prefix": item.key_prefix,
        "custom_prefix": item.custom_prefix,
        "revealable": item.key_ciphertext is not None, "status": item.status,
        "expires_at": item.expires_at, "aggregate_model_ids": grants.get("aggregate_ids", []),
        "access_model_ids": grants.get("access_ids", []), "tpm_limit": item.tpm_limit,
        "qps_limit": item.qps_limit, "token_budget": item.token_budget,
        "amount_budget": item.amount_budget, "budget_period": item.budget_period,
        "wait_mode": item.wait_mode,
        "max_wait_ms": item.max_wait_ms, "created_at": item.created_at,
    }


def validate_models(db: Session, settings: KeySettings) -> None:
    aggregates = settings.aggregate_model_ids
    access = settings.access_model_ids
    if len(set(aggregates)) != len(aggregates) or len(set(access)) != len(access):
        raise HTTPException(422, "模型绑定不能重复。")
    if any(id_ <= 0 for id_ in aggregates + access):
        raise HTTPException(422, "模型 ID 必须是正整数。")
    if aggregates:
        found = db.scalars(select(AggregatedModel).where(AggregatedModel.id.in_(aggregates))).all()
        if len(found) != len(aggregates) or any(
            item.status != 1 or item.default_routing_strategy not in STRATEGIES for item in found
        ):
            raise HTTPException(422, "聚合模型必须已启用并配置内置路由策略。")
    if access:
        found = db.scalars(select(ProviderModel).where(ProviderModel.id.in_(access))).all()
        if len(found) != len(access) or any(item.status != 1 for item in found):
            raise HTTPException(422, "直连接入模型必须已启用。")


def validate_owner(db: Session, scope: str, payload: CreateKey) -> int | None:
    if scope == "user":
        if payload.user_id is None or payload.project_id is not None:
            raise HTTPException(422, "个人 Key 必须指定用户，且不能指定项目。")
        user = db.get(User, payload.user_id)
        if user is None or user.deleted_at is not None or user.status != 1:
            raise HTTPException(422, "用户不存在或已停用。")
        if payload.organization_id is not None:
            organization = db.get(Organization, payload.organization_id)
            if (organization is None or organization.deleted_at is not None
                    or organization.status != 1):
                raise HTTPException(422, "组织不存在或已停用。")
        return payload.organization_id
    if payload.project_id is None or payload.organization_id is not None:
        raise HTTPException(422, "项目 Key 必须指定项目，组织由项目自动继承。")
    project = db.get(Project, payload.project_id)
    if project is None or project.deleted_at is not None or project.status != 1:
        raise HTTPException(422, "项目不存在或已停用。")
    if payload.user_id is not None:
        owner = db.get(User, payload.user_id)
        member = db.scalar(select(ProjectMember.id).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == payload.user_id, ProjectMember.status == 1,
        ))
        if (owner is None or owner.deleted_at is not None or owner.status != 1
                or member is None):
            raise HTTPException(422, "归属人必须是该项目的有效成员。")
    if project.organization_id is not None:
        organization = db.get(Organization, project.organization_id)
        if organization is None or organization.deleted_at is not None or organization.status != 1:
            raise HTTPException(422, "所属组织已停用。")
    return project.organization_id


def apply_settings(item: ApiKey, settings: KeySettings) -> None:
    item.name = settings.name.strip()
    item.allowed_models = {
        "aggregate_ids": settings.aggregate_model_ids, "access_ids": settings.access_model_ids,
    }
    for field in ("expires_at", "tpm_limit", "qps_limit", "token_budget",
                  "amount_budget", "budget_period", "wait_mode", "max_wait_ms"):
        setattr(item, field, getattr(settings, field))


def save(db: Session, item: ApiKey) -> None:
    try:
        db.add(item)
        db.commit()
        db.refresh(item)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Key 配置冲突，请重试。") from exc


def generate_secret(custom_prefix: str | None = None) -> tuple[str, str, str]:
    prefix = (
        (custom_prefix if custom_prefix.endswith("_") else f"{custom_prefix}_")
        if custom_prefix else DEFAULT_KEY_PREFIX
    )
    raw = prefix + secrets.token_urlsafe(32)
    return raw, raw[:max(12, len(prefix) + 4)], hashlib.sha256(raw.encode()).hexdigest()


def cipher() -> Fernet:
    key = get_settings().provider_encryption_key
    if not key:
        raise HTTPException(503, "未配置密钥加密密钥，无法创建可查看的 Key。")
    try:
        return Fernet(key.encode())
    except ValueError as exc:
        raise HTTPException(503, "密钥加密配置无效。") from exc


def models_for_key(db: Session, item: ApiKey) -> list[dict]:
    grants = item.allowed_models if isinstance(item.allowed_models, dict) else {}
    models = [
        {"id": model.public_model_name, "model_type": model.model_type}
        for model in db.scalars(select(AggregatedModel).where(
            AggregatedModel.id.in_(grants.get("aggregate_ids", [])),
            AggregatedModel.status == 1,
        ))
    ]
    models.extend(
        {"id": model.access_model_code, "model_type": model.model_type}
        for model in db.scalars(select(ProviderModel).where(
            ProviderModel.id.in_(grants.get("access_ids", [])),
            ProviderModel.status == 1,
        ))
    )
    return models


def reveal_key(scope: str, key_id: int, db: Session) -> dict:
    item = require_key(db, key_id, scope)
    if item.key_ciphertext is None:
        raise HTTPException(409, "历史 Key 只存有哈希，无法恢复；轮换后可多次查看新 Key。")
    try:
        raw = cipher().decrypt(item.key_ciphertext.encode()).decode()
    except (InvalidToken, ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(503, "Key 无法解密，请检查密钥加密配置。") from exc
    if not hmac.compare_digest(hashlib.sha256(raw.encode()).hexdigest(), item.key_hash):
        raise HTTPException(503, "Key 校验失败，请检查密钥数据。")
    return success_response({
        "api_key": raw, "models": models_for_key(db, item),
    }).model_dump(mode="json")


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def list_keys(scope: str, db: Session, page: int, page_size: int,
              owner_id: int | None, filters: str | None = None) -> dict:
    statement = select(ApiKey).where(ApiKey.scope_type == scope, ApiKey.deleted_at.is_(None))
    if owner_id is not None:
        field = ApiKey.user_id if scope == "user" else ApiKey.project_id
        statement = statement.where(field == owner_id)
    if filters:
        owner_field = ApiKey.user_id if scope == "user" else ApiKey.project_id
        expression = filter_expression(filters, {
            "id": (ApiKey.id, "number"), "name": (ApiKey.name, "text"),
            "key_prefix": (ApiKey.key_prefix, "text"),
            "owner_id": (owner_field, "number"),
            "tpm_limit": (ApiKey.tpm_limit, "number"),
            "qps_limit": (ApiKey.qps_limit, "number"),
            "token_budget": (ApiKey.token_budget, "number"),
            "amount_budget": (ApiKey.amount_budget, "decimal"),
            "budget_period": (ApiKey.budget_period, "select", {"week", "month"}),
            "wait_mode": (ApiKey.wait_mode, "select", {"queue", "block"}),
            "status": (ApiKey.status, "select", {"0", "1"}),
        })
        if expression is not None:
            statement = statement.where(expression)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    items = db.scalars(statement.order_by(ApiKey.id.desc()).offset(
        (page - 1) * page_size).limit(page_size)).all()
    owner_names = {
        user.id: user.username for user in db.scalars(select(User).where(
            User.id.in_([item.user_id for item in items if item.user_id is not None]),
        ))
    } if scope == "project" and items else {}
    return success_response({
        "items": [{**serialize(item), "owner_name": owner_names.get(item.user_id)}
                  for item in items], "total": total,
        "page": page, "page_size": page_size,
    }).model_dump(mode="json")


def create_key(scope: str, payload: CreateKey, db: Session, user: User) -> dict:
    organization_id = validate_owner(db, scope, payload)
    validate_models(db, payload)
    raw, prefix, digest = generate_secret(payload.custom_prefix)
    ciphertext = cipher().encrypt(raw.encode()).decode()
    item = ApiKey(
        scope_type=scope, organization_id=organization_id, user_id=payload.user_id,
        project_id=payload.project_id, key_prefix=prefix, custom_prefix=payload.custom_prefix,
        key_hash=digest,
        key_ciphertext=ciphertext,
        created_by=user.id, status=1,
    )
    apply_settings(item, payload)
    save(db, item)
    return success_response({
        **serialize(item), "api_key": raw, "models": models_for_key(db, item),
    }).model_dump(mode="json")


def update_key(scope: str, key_id: int, payload: KeySettings, db: Session) -> dict:
    item = require_key(db, key_id, scope)
    validate_models(db, payload)
    apply_settings(item, payload)
    save(db, item)
    return success_response(serialize(item)).model_dump(mode="json")


def rotate_key(scope: str, key_id: int, db: Session, payload: RotateKey | None = None) -> dict:
    item = require_key(db, key_id, scope)
    custom_prefix = item.custom_prefix if payload is None else payload.custom_prefix
    raw, prefix, digest = generate_secret(custom_prefix)
    ciphertext = cipher().encrypt(raw.encode()).decode()
    item.key_prefix, item.custom_prefix = prefix, custom_prefix
    item.key_hash, item.key_ciphertext = digest, ciphertext
    save(db, item)
    return success_response({
        **serialize(item), "api_key": raw, "models": models_for_key(db, item),
    }).model_dump(mode="json")


def set_status(scope: str, key_id: int, payload: StatusPayload, db: Session) -> dict:
    item = require_key(db, key_id, scope)
    if payload.status == 1:
        if item.expires_at is not None:
            if not future(item.expires_at):
                raise HTTPException(422, "Key 已过期，不能启用。")
        grants = item.allowed_models if isinstance(item.allowed_models, dict) else {}
        settings = KeySettings(
            name=item.name, aggregate_model_ids=grants.get("aggregate_ids", []),
            access_model_ids=grants.get("access_ids", []), expires_at=item.expires_at,
            tpm_limit=item.tpm_limit, qps_limit=item.qps_limit, token_budget=item.token_budget,
            amount_budget=item.amount_budget, budget_period=item.budget_period,
            wait_mode=item.wait_mode,
            max_wait_ms=item.max_wait_ms,
        )
        validate_models(db, settings)
        owner = CreateKey(**settings.model_dump(), user_id=item.user_id,
                          project_id=item.project_id, organization_id=(
                              item.organization_id if scope == "user" else None))
        validate_owner(db, scope, owner)
    item.status = payload.status
    save(db, item)
    return success_response(serialize(item)).model_dump(mode="json")


@router.get("/user-keys")
def list_user_keys(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                   user_id: int | None = None, filters: str | None = Query(None, max_length=4096),
                   db: Session = Depends(get_db),
                   user: User = Depends(actor)) -> dict:
    require_platform(user)
    return list_keys("user", db, page, page_size, user_id, filters)


@router.get("/project-keys")
def list_project_keys(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                      project_id: int | None = None, filters: str | None = Query(None, max_length=4096),
                      db: Session = Depends(get_db),
                      user: User = Depends(actor)) -> dict:
    require_platform(user)
    return list_keys("project", db, page, page_size, project_id, filters)


@router.post("/user-keys", status_code=201)
def create_user_key(payload: CreateKey, response: Response, db: Session = Depends(get_db),
                    user: User = Depends(actor)) -> dict:
    require_platform(user)
    no_store(response)
    return create_key("user", payload, db, user)


@router.post("/project-keys", status_code=201)
def create_project_key(payload: CreateKey, response: Response, db: Session = Depends(get_db),
                       user: User = Depends(actor)) -> dict:
    require_platform(user)
    no_store(response)
    return create_key("project", payload, db, user)


@router.get("/user-keys/{key_id}")
def user_key_detail(key_id: int, db: Session = Depends(get_db),
                    user: User = Depends(actor)) -> dict:
    require_platform(user)
    return success_response(serialize(require_key(db, key_id, "user"))).model_dump(mode="json")


@router.get("/project-keys/{key_id}")
def project_key_detail(key_id: int, db: Session = Depends(get_db),
                       user: User = Depends(actor)) -> dict:
    require_platform(user)
    return success_response(serialize(require_key(db, key_id, "project"))).model_dump(mode="json")


@router.get("/user-keys/{key_id}/secret")
def reveal_user_key(key_id: int, response: Response, db: Session = Depends(get_db),
                    user: User = Depends(actor)) -> dict:
    require_platform(user)
    no_store(response)
    return reveal_key("user", key_id, db)


@router.get("/project-keys/{key_id}/secret")
def reveal_project_key(key_id: int, response: Response, db: Session = Depends(get_db),
                       user: User = Depends(actor)) -> dict:
    require_platform(user)
    no_store(response)
    return reveal_key("project", key_id, db)


@router.put("/user-keys/{key_id}")
def update_user_key(key_id: int, payload: KeySettings, db: Session = Depends(get_db),
                    user: User = Depends(actor)) -> dict:
    require_platform(user)
    return update_key("user", key_id, payload, db)


@router.put("/project-keys/{key_id}")
def update_project_key(key_id: int, payload: KeySettings, db: Session = Depends(get_db),
                       user: User = Depends(actor)) -> dict:
    require_platform(user)
    return update_key("project", key_id, payload, db)


@router.post("/user-keys/{key_id}/rotate")
def rotate_user_key(key_id: int, response: Response, payload: RotateKey | None = None,
                    db: Session = Depends(get_db),
                    user: User = Depends(actor)) -> dict:
    require_platform(user)
    no_store(response)
    return rotate_key("user", key_id, db, payload)


@router.post("/project-keys/{key_id}/rotate")
def rotate_project_key(key_id: int, response: Response, payload: RotateKey | None = None,
                       db: Session = Depends(get_db),
                       user: User = Depends(actor)) -> dict:
    require_platform(user)
    no_store(response)
    return rotate_key("project", key_id, db, payload)


@router.patch("/user-keys/{key_id}/status")
def status_user_key(key_id: int, payload: StatusPayload, db: Session = Depends(get_db),
                    user: User = Depends(actor)) -> dict:
    require_platform(user)
    return set_status("user", key_id, payload, db)


@router.patch("/project-keys/{key_id}/status")
def status_project_key(key_id: int, payload: StatusPayload, db: Session = Depends(get_db),
                       user: User = Depends(actor)) -> dict:
    require_platform(user)
    return set_status("project", key_id, payload, db)
