from __future__ import annotations

# ruff: noqa: B008
import asyncio
import json
from datetime import UTC, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.responses import success_response
from app.db.models import RequestLog, UsageRecord, User
from app.db.session import get_db
from app.modules.gateway.archive import s3_client
from app.modules.identity.router import actor, require_platform

router = APIRouter(prefix="/logs", tags=["日志审计"])


def serialize(item: RequestLog, usage: UsageRecord | None) -> dict:
    return {
        "request_id": item.request_id,
        "created_at": item.created_at.isoformat(),
        "organization_id": item.organization_id,
        "project_id": item.project_id,
        "api_key_id": item.api_key_id,
        "model": item.public_model_name,
        "model_type": item.model_type,
        "provider_id": item.provider_id,
        "endpoint": item.endpoint,
        "http_status": item.http_status,
        "latency_ms": item.latency_ms,
        "error_code": item.error_code,
        "total_tokens": usage.total_tokens if usage else None,
    }


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
    db: Session = Depends(get_db),
    user: User = Depends(actor),
) -> dict:
    require_platform(user)
    condition = RequestLog.request_id == request_id if request_id else True
    total = db.scalar(select(func.count()).select_from(RequestLog).where(condition)) or 0
    rows = db.execute(
        select(RequestLog, UsageRecord).outerjoin(
            UsageRecord, UsageRecord.request_log_id == RequestLog.id,
        ).where(condition).order_by(RequestLog.created_at.desc(), RequestLog.id.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all()
    return success_response({
        "items": [serialize(item, usage) for item, usage in rows],
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
    result = serialize(item, usage)
    result["archive"] = None
    settings = get_settings()
    if settings.log_archive_enabled:
        created = item.created_at.replace(tzinfo=UTC) if item.created_at.tzinfo is None \
            else item.created_at
        # Calls crossing UTC midnight may be archived under the previous day.
        for day in (created, created - timedelta(days=1)):
            relative = f"{day:%Y/%m/%d}/{request_id}"
            local = Path(settings.log_archive_spool_dir) / relative / "manifest.pending"
            if local.exists():
                result["archive"] = {"status": "pending", "files": []}
                break
            prefix = "/".join(filter(None, (settings.log_archive_prefix.strip("/"), relative)))
            try:
                result["archive"] = await asyncio.to_thread(
                    archived_files, prefix, settings.log_archive_bucket,
                )
                if result["archive"]:
                    break
            except Exception:
                result["archive"] = {"status": "unavailable", "files": []}
                break
    return success_response(result).model_dump()
