from __future__ import annotations

import json
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.responses import success_response
from app.db.models import PlaygroundRecord, User
from app.db.session import get_db
from app.modules.identity.router import actor, require_platform

router = APIRouter(prefix="/playground/history", tags=["在线调试"])
MAX_CAPTURE = 262144
SENSITIVE = re.compile(
    r"(^|[-_])(authorization|api[-_]?key|token|secret|password|credential|cookie|auth)([-_]|$)", re.I,
)


def scrub(text: str, secrets: str | list[str] | None) -> str:
    values = [secrets] if isinstance(secrets, str) else secrets or []
    for secret in values:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text


def mask(value: object, secret: str | list[str] | None = None) -> object:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if SENSITIVE.search(str(key)) else mask(item, secret)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [mask(item, secret) for item in value]
    if isinstance(value, str):
        return scrub(value, secret)
    return value


def capture(text: str, secret: str | list[str] | None) -> tuple[str, bool]:
    safe = scrub(text, secret)
    return safe[:MAX_CAPTURE], len(safe) > MAX_CAPTURE


def start_record(db: Session, user_id: int, mode: str, source: str, model_code: str,
                 protocol: str, stream: bool, url: str, headers: dict, body: dict,
                 secret: str | list[str] | None) -> PlaygroundRecord:
    record = PlaygroundRecord(
        user_id=user_id, mode=mode, source=source, model_code=model_code,
        protocol=protocol, stream=stream, request_url=url,
        request_headers=mask(headers, secret), request_body=mask(body, secret),
        http_status=None, response_body=None, latency_ms=None, truncated=False,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def finish_record(db: Session, record: PlaygroundRecord, status: int, text: str,
                  latency_ms: int, secret: str | list[str] | None) -> None:
    record.response_body, clipped = capture(text, secret)
    record.truncated = record.truncated or clipped
    record.http_status = status
    record.latency_ms = latency_ms
    db.add(record)
    db.commit()


def parsed_content(record: PlaygroundRecord) -> str | None:
    if not record.response_body or record.http_status is None or record.http_status >= 400:
        return None

    def extract(value: dict) -> str:
        if record.protocol in ("openai", "openai_compatible"):
            choice = (value.get("choices") or [{}])[0]
            message = choice.get("delta") if record.stream else choice.get("message")
            content = (message or {}).get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return "".join(part.get("text", "") for part in content if isinstance(part, dict))
        if record.protocol in ("claude", "anthropic"):
            if record.stream:
                return (value.get("delta") or {}).get("text") or ""
            return "".join(part.get("text", "") for part in value.get("content", [])
                           if isinstance(part, dict) and part.get("type") == "text")
        if record.protocol == "gemini":
            candidate = (value.get("candidates") or [{}])[0]
            return "".join(part.get("text", "") for part in (candidate.get("content") or {}).get("parts", [])
                           if isinstance(part, dict))
        return ""

    try:
        if not record.stream:
            value = json.loads(record.response_body)
            return (extract(value) or None) if isinstance(value, dict) else None
        content = ""
        for frame in re.split(r"\r?\n\r?\n", record.response_body):
            data = "\n".join(line[5:].lstrip() for line in frame.splitlines() if line.startswith("data:"))
            if not data or data == "[DONE]":
                continue
            try:
                value = json.loads(data)
            except ValueError:
                continue
            if not isinstance(value, dict):
                continue
            fragment = extract(value)
            if record.protocol == "gemini" and fragment.startswith(content):
                content = fragment
            else:
                content += fragment
        return content or None
    except (ValueError, TypeError, IndexError, AttributeError):
        return None


def serialize(record: PlaygroundRecord, detail: bool = False) -> dict:
    result = {
        "id": record.id, "created_at": record.created_at.isoformat() if isinstance(record.created_at, datetime) else None,
        "mode": record.mode, "source": record.source, "model_code": record.model_code,
        "protocol": record.protocol, "stream": record.stream,
        "http_status": record.http_status, "latency_ms": record.latency_ms,
        "truncated": record.truncated,
    }
    if detail:
        result.update({
            "request_url": record.request_url,
            "request_headers": record.request_headers,
            "request_body": record.request_body,
            "response_body": record.response_body,
            "parsed_content": parsed_content(record),
        })
    return result


@router.get("")
def list_history(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                 db: Session = Depends(get_db), user: User = Depends(actor)) -> dict:
    require_platform(user)
    query = select(PlaygroundRecord).where(PlaygroundRecord.user_id == user.id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    records = db.scalars(query.order_by(PlaygroundRecord.id.desc())
                         .offset((page - 1) * page_size).limit(page_size)).all()
    return success_response({"items": [serialize(item) for item in records],
                             "total": total, "page": page, "page_size": page_size}).model_dump()


@router.get("/{record_id}")
def history_detail(record_id: int, db: Session = Depends(get_db),
                   user: User = Depends(actor)) -> dict:
    require_platform(user)
    record = db.get(PlaygroundRecord, record_id)
    if record is None or record.user_id != user.id:
        raise HTTPException(404, "调试记录不存在。")
    return success_response(serialize(record, detail=True)).model_dump()


@router.delete("/{record_id}")
def delete_history(record_id: int, db: Session = Depends(get_db),
                   user: User = Depends(actor)) -> dict:
    require_platform(user)
    record = db.get(PlaygroundRecord, record_id)
    if record is None or record.user_id != user.id:
        raise HTTPException(404, "调试记录不存在。")
    if record.http_status is None:
        raise HTTPException(409, "调试尚未结束，暂不能删除。")
    db.delete(record)
    db.commit()
    return success_response({"id": record_id}).model_dump()
