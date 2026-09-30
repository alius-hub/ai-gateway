from __future__ import annotations

# ruff: noqa: B008
import asyncio
import base64
import binascii
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.list_filters import filter_expression
from app.core.responses import success_response
from app.db.models import ApiKey, AuditEvent, RequestLog, UsageRecord, User
from app.db.session import get_db
from app.modules.gateway.archive import s3_client
from app.modules.identity.router import actor, require_platform

router = APIRouter(prefix="/logs", tags=["日志审计"])


@router.get("/audit-actors")
def list_audit_actors(
    db: Session = Depends(get_db), user: User = Depends(actor),
) -> dict:
    require_platform(user)
    rows = db.execute(
        select(AuditEvent.actor_user_id, func.max(AuditEvent.actor_username))
        .where(AuditEvent.actor_user_id.is_not(None))
        .group_by(AuditEvent.actor_user_id)
        .order_by(func.max(AuditEvent.actor_username), AuditEvent.actor_user_id)
    ).all()
    return success_response([
        {"id": actor_id, "username": username} for actor_id, username in rows
    ]).model_dump()


@router.get("/audit-resources")
def list_audit_resources(
    db: Session = Depends(get_db), user: User = Depends(actor),
) -> dict:
    require_platform(user)
    resources = db.scalars(
        select(AuditEvent.resource).distinct().order_by(AuditEvent.resource)
    ).all()
    return success_response(resources).model_dump()


@router.get("/audit-events")
def list_audit_events(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    actor_user_id: int | None = None, action: str | None = None,
    resource: str | None = None, start_time: datetime | None = None,
    end_time: datetime | None = None,
    filters: str | None = Query(None, max_length=4096),
    db: Session = Depends(get_db),
    user: User = Depends(actor),
) -> dict:
    require_platform(user)
    if start_time and end_time and start_time > end_time:
        raise HTTPException(422, "开始时间不能晚于结束时间。")
    statement = select(AuditEvent)
    if actor_user_id is not None:
        statement = statement.where(AuditEvent.actor_user_id == actor_user_id)
    if action:
        statement = statement.where(AuditEvent.action == action)
    if resource:
        statement = statement.where(AuditEvent.resource == resource)
    if start_time:
        statement = statement.where(AuditEvent.created_at >= start_time)
    if end_time:
        statement = statement.where(AuditEvent.created_at <= end_time)
    if filters:
        expression = filter_expression(filters, {
            "id": (AuditEvent.id, "number"),
            "created_at": (AuditEvent.created_at, "date"),
            "actor_user_id": (AuditEvent.actor_user_id, "number"),
            "actor_username": (AuditEvent.actor_username, "text"),
            "action": (AuditEvent.action, "select", {
                "login", "create", "update", "delete", "rotate", "reset_password",
            }),
            "resource": (AuditEvent.resource, "text"),
            "method": (AuditEvent.method, "select", {"POST", "PUT", "PATCH", "DELETE"}),
            "path": (AuditEvent.path, "text"),
            "ip_address": (AuditEvent.ip_address, "text"),
            "status_code": (AuditEvent.status_code, "number"),
        })
        if expression is not None:
            statement = statement.where(expression)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    items = db.scalars(statement.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
                       .offset((page - 1) * page_size).limit(page_size)).all()
    return success_response({
        "items": [{
            "id": item.id, "actor_user_id": item.actor_user_id,
            "actor_username": item.actor_username, "action": item.action,
            "resource": item.resource, "method": item.method, "path": item.path,
            "ip_address": item.ip_address, "status_code": item.status_code,
            "created_at": item.created_at.isoformat(),
        } for item in items],
        "page": page, "page_size": page_size, "total": total,
    }).model_dump()


MAX_REQUEST_BYTES = 16 * 1024 * 1024
MAX_IMAGE_BYTES = 8 * 1024 * 1024
IMAGE_DATA = re.compile(r"^data:(image/(?:png|jpeg|gif|webp|avif));base64,([A-Za-z0-9+/=]+)$",
                        re.IGNORECASE)


def serialize(item: RequestLog, usage: UsageRecord | None, api_key: ApiKey | None = None) -> dict:
    tps = None
    if (item.endpoint == "/v1/chat/completions" and item.http_status == 200
            and usage is not None and usage.output_tokens is not None
            and item.latency_ms is not None and item.latency_ms > 0):
        tps = round(usage.output_tokens * 1000 / item.latency_ms, 2)
    return {
        "request_id": item.request_id,
        "created_at": item.created_at.isoformat(),
        "organization_id": item.organization_id,
        "project_id": item.project_id,
        "api_key_id": item.api_key_id,
        "api_key_masked": item.api_key_masked or (
            f"{api_key.key_prefix}****" if api_key is not None else None),
        "api_key_snapshot": item.api_key_masked is not None,
        "model": item.public_model_name,
        "model_type": item.model_type,
        "provider_id": item.provider_id,
        "provider_model_id": item.provider_model_id,
        "provider_status": item.provider_status,
        "error_message": item.error_message,
        "requester_ip": item.requester_ip,
        "endpoint": item.endpoint,
        "http_status": item.http_status,
        "latency_ms": item.latency_ms,
        "tps": tps,
        "ttft_ms": item.ttft_ms,
        "tpot_ms": float(item.tpot_ms) if item.tpot_ms is not None else None,
        "error_code": item.error_code,
        "total_tokens": usage.total_tokens if usage else None,
        "input_tokens": usage.input_tokens if usage else None,
        "output_tokens": usage.output_tokens if usage else None,
        "reasoning_tokens": usage.reasoning_tokens if usage else None,
        "non_reasoning_tokens": usage.non_reasoning_tokens if usage else None,
    }


def image_sources(value: object):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"image_url", "image", "b64_json"}:
                if isinstance(item, str):
                    yield item
                elif isinstance(item, dict):
                    for field in ("url", "data"):
                        if isinstance(item.get(field), str):
                            yield item[field]
                else:
                    yield from image_sources(item)
            else:
                yield from image_sources(item)
    elif isinstance(value, list):
        for item in value:
            yield from image_sources(item)


def image_entries(body: bytes) -> list[tuple[str, str]]:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, ValueError):
        return []
    images = []
    for source in image_sources(payload):
        if IMAGE_DATA.fullmatch(source) and len(source) <= MAX_IMAGE_BYTES * 4 // 3 + 100:
            images.append(("inline", source))
        elif source.startswith("data:"):
            continue
        elif urlparse(source).scheme in {"http", "https"} and len(source) <= 2048:
            images.append(("url", source))
        elif re.fullmatch(r"[A-Za-z0-9+/=]+", source) and len(source) <= MAX_IMAGE_BYTES * 4 // 3:
            images.append(("base64", source))
        if len(images) >= 32:
            break
    return images


def archived_request(prefix: str, bucket: str) -> bytes | None:
    client = s3_client()
    try:
        obj = client.get_object(Bucket=bucket, Key=f"{prefix}/request.bin")
    except client.exceptions.NoSuchKey:
        return None
    body = obj["Body"].read(MAX_REQUEST_BYTES + 1)
    return body if len(body) <= MAX_REQUEST_BYTES else None


def archive_prefix(item: RequestLog, offset: int) -> str:
    created = item.created_at.replace(tzinfo=UTC) if item.created_at.tzinfo is None \
        else item.created_at
    settings = get_settings()
    relative = f"{created - timedelta(days=offset):%Y/%m/%d}/{item.request_id}"
    return "/".join(filter(None, (settings.log_archive_prefix.strip("/"), relative)))


def archived_files(prefix: str, bucket: str) -> dict | None:
    client = s3_client()
    try:
        obj = client.get_object(Bucket=bucket, Key=f"{prefix}/manifest.json")
    except client.exceptions.NoSuchKey:
        return None
    manifest = json.loads(obj["Body"].read())
    names = [*manifest["files"], *(
        image["object"].rsplit("/", 1)[-1]
        for image in manifest.get("external_images", []) if image["saved"]
    )]
    return {
        "status": "stored", "manifest": manifest,
        "downloads": {
            name: client.generate_presigned_url(
                "get_object", Params={"Bucket": bucket, "Key": f"{prefix}/{name}"},
                ExpiresIn=60,
            ) for name in names
        },
    }


@router.get("/requests")
async def list_request_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    request_id: str | None = None,
    filters: str | None = Query(None, max_length=4096),
    db: Session = Depends(get_db),
    user: User = Depends(actor),
) -> dict:
    require_platform(user)
    statement = select(RequestLog, UsageRecord).outerjoin(
        UsageRecord, UsageRecord.request_log_id == RequestLog.id)
    if request_id:
        statement = statement.where(RequestLog.request_id == request_id)
    if filters:
        expression = filter_expression(filters, {
            "request_id": (RequestLog.request_id, "text"),
            "created_at": (RequestLog.created_at, "date"),
            "model": (RequestLog.public_model_name, "text"),
            "public_model": (RequestLog.public_model_name, "text"),
            "organization": (RequestLog.organization_id, "number"),
            "organization_unassigned": (RequestLog.organization_id.is_(None), "boolean", {"1"}),
            "project": (RequestLog.project_id, "number"),
            "project_unassigned": (RequestLog.project_id.is_(None), "boolean", {"1"}),
            "key": (RequestLog.api_key_id, "number"),
            "key_unassigned": (RequestLog.api_key_id.is_(None), "boolean", {"1"}),
            "provider": (RequestLog.provider_id, "number"),
            "provider_unassigned": (RequestLog.provider_id.is_(None), "boolean", {"1"}),
            "access_model": (RequestLog.provider_model_id, "number"),
            "access_model_unassigned": (RequestLog.provider_model_id.is_(None),
                                         "boolean", {"1"}),
            "endpoint": (RequestLog.endpoint, "text"),
            "model_type": (RequestLog.model_type, "text"),
            "currency": (UsageRecord.currency, "text"),
            "estimated_cost": (UsageRecord.estimated_cost, "decimal"),
            "http_status": (RequestLog.http_status, "number"),
            "latency_ms": (RequestLog.latency_ms, "number"),
            "total_tokens": (UsageRecord.total_tokens, "number"),
            "error_code": (RequestLog.error_code, "text"),
        })
        if expression is not None:
            statement = statement.where(expression)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = db.execute(
        statement.order_by(RequestLog.created_at.desc(), RequestLog.id.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all()
    key_ids = {item.api_key_id for item, _usage in rows if item.api_key_id is not None}
    keys = {key.id: key for key in db.scalars(select(ApiKey).where(ApiKey.id.in_(key_ids)))}
    return success_response({
        "items": [serialize(item, usage, keys.get(item.api_key_id)) for item, usage in rows],
        "page": page, "page_size": page_size, "total": total,
    }).model_dump()


@router.get("/requests/{request_id}")
async def get_request_log(
    request_id: str, db: Session = Depends(get_db), user: User = Depends(actor),
) -> dict:
    require_platform(user)
    item = db.scalar(select(RequestLog).where(RequestLog.request_id == request_id))
    if item is None:
        raise HTTPException(404, "调用日志不存在")
    usage = db.scalar(select(UsageRecord).where(UsageRecord.request_log_id == item.id))
    result = serialize(item, usage, db.get(ApiKey, item.api_key_id) if item.api_key_id else None)
    result["archive"] = None
    result["images"] = []
    settings = get_settings()
    if settings.log_archive_enabled:
        created = item.created_at.replace(tzinfo=UTC) if item.created_at.tzinfo is None \
            else item.created_at
        # Calls crossing UTC midnight may be archived under the previous day.
        for offset, day in enumerate((created, created - timedelta(days=1))):
            relative = f"{day:%Y/%m/%d}/{request_id}"
            local = Path(settings.log_archive_spool_dir) / relative / "manifest.pending"
            if local.exists():
                result["archive"] = {"status": "pending", "files": []}
                break
            prefix = archive_prefix(item, offset)
            try:
                result["archive"] = await asyncio.to_thread(
                    archived_files, prefix, settings.log_archive_bucket,
                )
                if result["archive"]:
                    try:
                        body = await asyncio.to_thread(
                            archived_request, prefix, settings.log_archive_bucket,
                        )
                        if body:
                            result["images"] = [
                                {"kind": kind, "url": source if kind == "url" else None,
                                 "index": index}
                                for index, (kind, source) in enumerate(image_entries(body))
                            ]
                    except Exception:
                        pass
                    break
            except Exception:
                result["archive"] = {"status": "unavailable", "files": []}
                break
    return success_response(result).model_dump()


MAX_RAW_PREVIEW_BYTES = 2 * 1024 * 1024


def archived_preview(prefix: str, bucket: str, filename: str) -> dict | None:
    client = s3_client()
    try:
        obj = client.get_object(Bucket=bucket, Key=f"{prefix}/{filename}")
    except client.exceptions.NoSuchKey:
        return None
    stream = obj["Body"]
    try:
        body = stream.read(MAX_RAW_PREVIEW_BYTES + 1)
    finally:
        stream.close()
    return {"filename": filename, "text": body[:MAX_RAW_PREVIEW_BYTES].decode("utf-8", "replace"),
            "truncated": len(body) > MAX_RAW_PREVIEW_BYTES,
            "size_bytes": obj.get("ContentLength")}


@router.get("/requests/{request_id}/raw/{filename}")
async def preview_request_raw(
    request_id: str,
    filename: Literal[
        "request.bin", "upstream_request.bin", "upstream_response.bin", "response.bin",
    ],
    db: Session = Depends(get_db), user: User = Depends(actor),
) -> dict:
    require_platform(user)
    settings = get_settings()
    if not settings.log_archive_enabled:
        raise HTTPException(404, "原始内容归档未启用")
    item = db.scalar(select(RequestLog).where(RequestLog.request_id == request_id))
    if item is None:
        raise HTTPException(404, "调用日志不存在")
    for offset in (0, 1):
        try:
            result = await asyncio.to_thread(
                archived_preview, archive_prefix(item, offset),
                settings.log_archive_bucket, filename,
            )
        except Exception:
            raise HTTPException(503, "原始内容暂时不可用，请稍后重试") from None
        if result is not None:
            return success_response(result).model_dump()
    raise HTTPException(404, "原始文件不存在或尚未上传，请稍后重新打开详情")


@router.get("/requests/{request_id}/images/{index}")
async def preview_request_image(
    request_id: str, index: int, db: Session = Depends(get_db), user: User = Depends(actor),
) -> Response:
    require_platform(user)
    if index < 0 or index >= 32 or not get_settings().log_archive_enabled:
        raise HTTPException(404, "图片不存在")
    item = db.scalar(select(RequestLog).where(RequestLog.request_id == request_id))
    if item is None:
        raise HTTPException(404, "图片不存在")
    for offset in (0, 1):
        try:
            body = await asyncio.to_thread(
                archived_request, archive_prefix(item, offset), get_settings().log_archive_bucket,
            )
        except Exception:
            raise HTTPException(503, "归档暂时不可用") from None
        if body is None:
            continue
        images = image_entries(body)
        if index >= len(images) or images[index][0] == "url":
            break
        kind, source = images[index]
        match = IMAGE_DATA.fullmatch(source) if kind == "inline" else None
        try:
            data = base64.b64decode(match[2] if match else source, validate=True)
        except (ValueError, binascii.Error):
            break
        if len(data) > MAX_IMAGE_BYTES:
            break
        detected = (
            "image/png" if data.startswith(b"\x89PNG\r\n\x1a\n") else
            "image/jpeg" if data.startswith(b"\xff\xd8\xff") else
            "image/gif" if data.startswith((b"GIF87a", b"GIF89a")) else
            "image/webp" if data.startswith(b"RIFF") and data[8:12] == b"WEBP" else
            "image/avif" if data[4:12] == b"ftypavif" else None
        )
        if detected and (match is None or match[1].lower() == detected):
            return Response(data, media_type=detected, headers={
                "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'none'; sandbox",
            })
        break
    raise HTTPException(404, "图片不存在")
