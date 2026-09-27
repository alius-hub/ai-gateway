from __future__ import annotations

import re
from typing import Literal

from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.responses import success_response
from app.db.models import Provider, ProviderProtocol, ProviderSecret, User
from app.db.session import get_db
from app.modules.identity.router import actor, require_platform

router = APIRouter(prefix="/providers", tags=["供应商管理"])
CODE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class ProviderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    code: str | None = Field(default=None, min_length=1, max_length=64)


class ProtocolPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=64)
    protocol_type: str = Field(min_length=1, max_length=64)
    base_url: HttpUrl


class ProtocolUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol_type: str | None = Field(default=None, min_length=1, max_length=64)
    base_url: HttpUrl | None = None
    status: Literal[0, 1] | None = None


class SecretPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    api_key: str = Field(min_length=1, max_length=4096)


class ProviderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=64)
    provider_type: str = Field(min_length=1, max_length=64)
    base_url: HttpUrl
    api_key: str | None = Field(default=None, min_length=1, max_length=4096)
    additional_protocols: list[ProtocolPayload] = Field(default_factory=list)
    secrets: list[SecretPayload] = Field(default_factory=list)
    status: Literal[0, 1] = 1


class SecretUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: str | None = Field(default=None, min_length=1, max_length=4096)
    status: Literal[0, 1] | None = None


class ProviderStatus(BaseModel):
    status: Literal[0, 1]


def serialize(item: Provider) -> dict:
    return {
        "id": item.id, "organization_id": item.organization_id,
        "name": item.name, "code": item.code, "provider_type": item.provider_type,
        "base_url": item.base_url, "status": item.status,
        "health_status": item.health_status,
    }


def get_provider(db: Session, provider_id: int) -> Provider:
    item = db.get(Provider, provider_id)
    if item is None:
        raise HTTPException(404, "供应商不存在。")
    return item


def validate_code(db: Session, code: str, exclude_id: int | None = None) -> None:
    if not CODE_PATTERN.fullmatch(code):
        raise HTTPException(422, "编码只能使用小写字母、数字、下划线和连字符。")
    existing = db.scalar(select(Provider.id).where(Provider.code == code))
    if existing is not None and existing != exclude_id:
        raise HTTPException(409, "供应商编码已存在。")


def encrypt_key(value: str) -> str:
    key = get_settings().provider_encryption_key
    if not key:
        raise HTTPException(503, "未配置供应商密钥加密密钥。")
    try:
        return Fernet(key.encode()).encrypt(value.encode()).decode()
    except ValueError as exc:
        raise HTTPException(503, "供应商密钥加密配置无效。") from exc


def save(db: Session, item, serializer=serialize) -> dict:
    try:
        db.add(item)
        db.commit()
        db.refresh(item)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "供应商配置与现有数据冲突。") from exc
    return success_response(serializer(item)).model_dump()


def serialize_protocol(item: ProviderProtocol) -> dict:
    return {
        "id": item.id, "provider_id": item.provider_id, "code": item.code,
        "protocol_type": item.protocol_type, "base_url": item.base_url, "status": item.status,
    }


def serialize_secret(item: ProviderSecret) -> dict:
    return {
        "id": item.id, "provider_id": item.provider_id, "name": item.name,
        "status": item.status,
    }


def child(db: Session, model: type, provider_id: int, child_id: int):
    item = db.get(model, child_id)
    if item is None or item.provider_id != provider_id:
        raise HTTPException(404, "配置不存在。")
    return item


@router.get("")
def list_providers(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    keyword: str = "", db: Session = Depends(get_db), _user: User = Depends(actor),
) -> dict:
    statement = select(Provider)
    if keyword.strip():
        statement = statement.where(
            Provider.name.ilike(f"%{keyword.strip()}%") | Provider.code.ilike(f"%{keyword.strip()}%")
        )
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    items = db.scalars(statement.order_by(Provider.id.desc()).offset(
        (page - 1) * page_size).limit(page_size)).all()
    ids = [item.id for item in items]
    secret_counts = dict(db.execute(
        select(ProviderSecret.provider_id, func.count()).where(
            ProviderSecret.provider_id.in_(ids)).group_by(ProviderSecret.provider_id)).all())
    protocol_counts = dict(db.execute(
        select(ProviderProtocol.provider_id, func.count()).where(
            ProviderProtocol.provider_id.in_(ids)).group_by(ProviderProtocol.provider_id)).all())
    return success_response({
        "items": [{**serialize(item), "secret_count": secret_counts.get(item.id, 0),
                   "protocol_count": protocol_counts.get(item.id, 0)} for item in items],
        "total": total,
        "page": page, "page_size": page_size,
    }).model_dump()


@router.post("", status_code=201)
def create_provider(
    payload: ProviderCreate, db: Session = Depends(get_db), user: User = Depends(actor),
) -> dict:
    require_platform(user)
    data = payload.model_dump(exclude={"api_key", "additional_protocols", "secrets"})
    data["base_url"] = str(payload.base_url)
    data["name"] = data["name"].strip()
    data["code"] = data["code"].strip()
    data["provider_type"] = data["provider_type"].strip()
    if not all((data["name"], data["code"], data["provider_type"])):
        raise HTTPException(422, "名称、编码和类型不能为空。")
    validate_code(db, data["code"])
    protocol_codes = ["default"]
    for protocol in payload.additional_protocols:
        code = protocol.code.strip()
        if not CODE_PATTERN.fullmatch(code) or not protocol.protocol_type.strip():
            raise HTTPException(422, "协议编码或类型格式无效。")
        protocol_codes.append(code)
    secret_names = (["default"] if payload.api_key else []) + [
        secret.name.strip() for secret in payload.secrets
    ]
    if any(not name for name in secret_names):
        raise HTTPException(422, "密钥名称不能为空。")
    if len(set(protocol_codes)) != len(protocol_codes) or len(set(secret_names)) != len(secret_names):
        raise HTTPException(422, "协议编码或密钥名称不能重复。")
    encrypted_secrets = [("default", encrypt_key(payload.api_key))] if payload.api_key else []
    encrypted_secrets += [
        (secret.name.strip(), encrypt_key(secret.api_key)) for secret in payload.secrets
    ]
    provider = Provider(**data, health_status="unknown")
    try:
        db.add(provider)
        db.flush()
        db.add(ProviderProtocol(
            provider_id=provider.id, code="default", protocol_type=provider.provider_type,
            base_url=provider.base_url, status=1))
        for protocol in payload.additional_protocols:
            db.add(ProviderProtocol(
                provider_id=provider.id, code=protocol.code.strip(),
                protocol_type=protocol.protocol_type.strip(),
                base_url=str(protocol.base_url), status=1))
        for name, ciphertext in encrypted_secrets:
            db.add(ProviderSecret(
                provider_id=provider.id, name=name, ciphertext=ciphertext, status=1))
        db.commit()
        db.refresh(provider)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "供应商配置与现有数据冲突。") from exc
    return success_response(serialize(provider)).model_dump()


@router.get("/{provider_id}/protocols")
def list_protocols(
    provider_id: int, db: Session = Depends(get_db), _user: User = Depends(actor),
) -> dict:
    get_provider(db, provider_id)
    items = db.scalars(select(ProviderProtocol).where(
        ProviderProtocol.provider_id == provider_id).order_by(ProviderProtocol.id)).all()
    return success_response([serialize_protocol(item) for item in items]).model_dump()


@router.post("/{provider_id}/protocols", status_code=201)
def create_protocol(
    provider_id: int, payload: ProtocolPayload, db: Session = Depends(get_db),
    user: User = Depends(actor),
) -> dict:
    require_platform(user)
    get_provider(db, provider_id)
    code = payload.code.strip()
    if not CODE_PATTERN.fullmatch(code):
        raise HTTPException(422, "协议编码格式无效。")
    if not payload.protocol_type.strip():
        raise HTTPException(422, "协议类型不能为空。")
    return save(db, ProviderProtocol(
        provider_id=provider_id, code=code, protocol_type=payload.protocol_type.strip(),
        base_url=str(payload.base_url), status=1), serialize_protocol)


@router.patch("/{provider_id}/protocols/{protocol_id}")
def update_protocol(
    provider_id: int, protocol_id: int, payload: ProtocolUpdate,
    db: Session = Depends(get_db), user: User = Depends(actor),
) -> dict:
    require_platform(user)
    item = child(db, ProviderProtocol, provider_id, protocol_id)
    changes = payload.model_dump(exclude_unset=True)
    if any(value is None for value in changes.values()):
        raise HTTPException(422, "协议配置不能为空。")
    if "protocol_type" in changes:
        changes["protocol_type"] = changes["protocol_type"].strip()
        if not changes["protocol_type"]:
            raise HTTPException(422, "协议类型不能为空。")
    if "base_url" in changes:
        changes["base_url"] = str(changes["base_url"])
    for field, value in changes.items():
        setattr(item, field, value)
    if item.code == "default":
        provider = get_provider(db, provider_id)
        provider.provider_type = item.protocol_type
        provider.base_url = item.base_url
    return save(db, item, serialize_protocol)


@router.get("/{provider_id}/secrets")
def list_secrets(
    provider_id: int, db: Session = Depends(get_db), user: User = Depends(actor),
) -> dict:
    require_platform(user)
    get_provider(db, provider_id)
    items = db.scalars(select(ProviderSecret).where(
        ProviderSecret.provider_id == provider_id).order_by(ProviderSecret.id)).all()
    return success_response([serialize_secret(item) for item in items]).model_dump()


@router.post("/{provider_id}/secrets", status_code=201)
def create_secret(
    provider_id: int, payload: SecretPayload, db: Session = Depends(get_db),
    user: User = Depends(actor),
) -> dict:
    require_platform(user)
    get_provider(db, provider_id)
    if not payload.name.strip():
        raise HTTPException(422, "密钥名称不能为空。")
    return save(db, ProviderSecret(
        provider_id=provider_id, name=payload.name.strip(),
        ciphertext=encrypt_key(payload.api_key), status=1), serialize_secret)


@router.patch("/{provider_id}/secrets/{secret_id}")
def update_secret(
    provider_id: int, secret_id: int, payload: SecretUpdate,
    db: Session = Depends(get_db), user: User = Depends(actor),
) -> dict:
    require_platform(user)
    item = child(db, ProviderSecret, provider_id, secret_id)
    if payload.api_key is not None:
        item.ciphertext = encrypt_key(payload.api_key)
    if payload.status is not None:
        item.status = payload.status
    return save(db, item, serialize_secret)


@router.get("/{provider_id}")
def provider_detail(
    provider_id: int, db: Session = Depends(get_db), _user: User = Depends(actor),
) -> dict:
    return success_response(serialize(get_provider(db, provider_id))).model_dump()


@router.patch("/{provider_id}")
def update_provider(
    provider_id: int, payload: ProviderUpdate, db: Session = Depends(get_db),
    user: User = Depends(actor),
) -> dict:
    require_platform(user)
    item = get_provider(db, provider_id)
    changes = payload.model_dump(exclude_unset=True)
    if "code" in changes:
        changes["code"] = changes["code"].strip()
        validate_code(db, changes["code"], item.id)
    for field in ("name",):
        if field in changes:
            changes[field] = changes[field].strip()
    if any(value is None or value == "" for value in changes.values()):
        raise HTTPException(422, "供应商字段不能为空。")
    for field, value in changes.items():
        setattr(item, field, value)
    return save(db, item)


@router.patch("/{provider_id}/status")
def update_provider_status(
    provider_id: int, payload: ProviderStatus, db: Session = Depends(get_db),
    user: User = Depends(actor),
) -> dict:
    require_platform(user)
    item = get_provider(db, provider_id)
    item.status = payload.status
    return save(db, item)


@router.get("/{provider_id}/health")
def provider_health(
    provider_id: int, db: Session = Depends(get_db), _user: User = Depends(actor),
) -> dict:
    item = get_provider(db, provider_id)
    return success_response({"provider_id": item.id, "health_status": item.health_status}).model_dump()
