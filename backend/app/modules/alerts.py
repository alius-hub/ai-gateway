"""Alert evaluation and Feishu SaaS application messaging."""

from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.list_filters import filter_expression
from app.core.responses import success_response
from app.db.models import (
    AlertDelivery,
    AlertEvent,
    AlertRule,
    ApiKey,
    FeishuSettings,
    Project,
    RequestLog,
    UsageRecord,
    User,
)
from app.db.session import SessionLocal, get_db
from app.modules.identity.router import actor, require_platform

logger = logging.getLogger(__name__)
# ruff: noqa: B008
router = APIRouter(prefix="/alerts", tags=["告警中心"])
FEISHU_API = "https://open.feishu.cn/open-apis"
ACTIVE = ("open", "acknowledged")


class RecipientPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    receive_id_type: Literal["open_id", "chat_id"]
    receive_id: str = Field(min_length=1, max_length=128)


class RulePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    metric: Literal["error_rate", "key_token_usage", "project_amount_usage"]
    scope_id: int | None = Field(default=None, gt=0)
    threshold: Decimal = Field(gt=0, le=100)
    window_minutes: int = Field(default=5, ge=1, le=60)
    min_samples: int = Field(default=10, ge=1, le=100000)
    level: Literal["warning", "critical"] = "warning"
    enabled: bool = True
    recipients: list[RecipientPayload] = Field(default_factory=list, max_length=50)

    @field_validator("recipients")
    @classmethod
    def unique_recipients(cls, items: list[RecipientPayload]) -> list[RecipientPayload]:
        targets = {(item.receive_id_type, item.receive_id) for item in items}
        if len(targets) != len(items):
            raise ValueError("接收目标不能重复。")
        return items


class FeishuPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app_id: str = Field(min_length=1, max_length=128)
    app_secret: str | None = Field(default=None, min_length=1, max_length=512)
    chat_id: str = Field(default="", max_length=128)
    enabled: bool = True


def _cipher() -> Fernet:
    key = get_settings().provider_encryption_key
    if not key:
        raise HTTPException(503, "请先配置服务端加密主密钥。")
    try:
        return Fernet(key.encode())
    except ValueError as exc:
        raise HTTPException(503, "服务端加密主密钥无效。") from exc


def _rule_data(item: AlertRule) -> dict:
    return {key: getattr(item, key) for key in (
        "id", "name", "metric", "scope_id", "threshold", "window_minutes",
        "min_samples", "level", "enabled", "created_at", "recipients",
    )}


def _event_data(item: AlertEvent, rule: AlertRule) -> dict:
    return {
        "id": item.id, "rule_id": item.rule_id, "rule_name": rule.name,
        "metric": rule.metric, "scope_id": rule.scope_id, "level": rule.level,
        "status": item.status, "current_value": item.current_value,
        "threshold": item.threshold, "triggered_at": item.triggered_at,
        "acknowledged_at": item.acknowledged_at, "acknowledged_by": item.acknowledged_by,
        "resolved_at": item.resolved_at,
    }


def _validate_scope(db: Session, data: RulePayload) -> None:
    if data.metric == "error_rate":
        if data.scope_id is not None and not db.get(Project, data.scope_id):
            raise HTTPException(422, "项目不存在。")
    elif data.scope_id is None:
        raise HTTPException(422, "该指标必须指定对象 ID。")
    elif data.metric == "key_token_usage":
        item = db.get(ApiKey, data.scope_id)
        if not item or item.deleted_at or not item.token_budget or not item.budget_period:
            raise HTTPException(422, "Key 不存在或未配置周期 Token 额度。")
    else:
        item = db.get(Project, data.scope_id)
        if not item or item.deleted_at or not item.amount_budget:
            raise HTTPException(422, "项目不存在或未配置金额预算。")


def _metric(db: Session, rule: AlertRule, now: datetime) -> Decimal | None:
    if rule.metric == "error_rate":
        start = (now - timedelta(minutes=rule.window_minutes)).replace(tzinfo=None)
        end = now.replace(tzinfo=None)
        filters = [RequestLog.created_at >= start, RequestLog.created_at < end,
                   RequestLog.http_status != 202, RequestLog.http_status != 429]
        if rule.scope_id is not None:
            filters.append(RequestLog.project_id == rule.scope_id)
        count, failures = db.execute(select(
            func.count(RequestLog.id),
            func.coalesce(func.sum(case((RequestLog.http_status >= 500, 1), else_=0)), 0),
        ).where(*filters)).one()
        # A completely idle window clears an earlier error-rate incident. A
        # non-empty window below min_samples is inconclusive and keeps its state.
        if count == 0:
            return Decimal(0)
        if count < rule.min_samples:
            return None
        return Decimal(failures * 100) / Decimal(count)
    if rule.metric == "key_token_usage":
        key = db.get(ApiKey, rule.scope_id)
        if not key or key.deleted_at or not key.token_budget or key.status != 1:
            return None
        if key.budget_period == "week":
            start = (now - timedelta(days=now.weekday())).replace(
                hour=0, minute=0, second=0, microsecond=0)
        elif key.budget_period == "month":
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            return None
        used = db.scalar(select(func.coalesce(func.sum(UsageRecord.total_tokens), 0)).where(
            UsageRecord.api_key_id == key.id,
            UsageRecord.created_at >= start.replace(tzinfo=None),
        ))
        return Decimal(used or 0) * 100 / Decimal(key.token_budget)
    if rule.metric == "project_amount_usage":
        project = db.get(Project, rule.scope_id)
        if not project or project.deleted_at or not project.amount_budget or project.status != 1:
            return None
        used = db.scalar(select(func.coalesce(func.sum(UsageRecord.estimated_cost), 0)).where(
            UsageRecord.project_id == project.id, UsageRecord.currency == "CNY",
        ))
        return Decimal(used or 0) * 100 / project.amount_budget
    return None


def _recipients(db: Session, rule: AlertRule) -> list[dict]:
    if rule.recipients:
        return rule.recipients
    config = db.get(FeishuSettings, 1)
    return [{"receive_id_type": "chat_id", "receive_id": config.chat_id if config else ""}]


def _enqueue(db: Session, event: AlertEvent, kind: str, now: datetime) -> None:
    for target in event.recipients:
        db.add(AlertDelivery(
            event_id=event.id, kind=kind, current_value=event.current_value,
            receive_id_type=target["receive_id_type"], receive_id=target["receive_id"],
            status="pending", attempts=0, next_attempt_at=now,
        ))


def evaluate_alerts(db: Session, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    # One evaluator across API workers; transaction-level lock releases on commit/rollback.
    if db.bind.dialect.name == "postgresql" and not db.scalar(
        select(func.pg_try_advisory_xact_lock(7201924))
    ):
        return
    for rule in db.scalars(select(AlertRule).where(AlertRule.enabled.is_(True))):
        value = _metric(db, rule, now)
        if value is None:
            continue
        if rule.suppressed_until_recovery:
            if value >= rule.threshold:
                continue
            rule.suppressed_until_recovery = False
        event = db.scalar(select(AlertEvent).where(
            AlertEvent.rule_id == rule.id, AlertEvent.status.in_(ACTIVE),
        ))
        if value >= rule.threshold:
            if event is None:
                event = AlertEvent(
                    rule_id=rule.id, status="open", current_value=value,
                    threshold=rule.threshold, triggered_at=now,
                    recipients=_recipients(db, rule),
                )
                db.add(event)
                db.flush()
                _enqueue(db, event, "triggered", now)
            else:
                event.current_value = value
        elif event:
            event.current_value = value
            event.status = "resolved"
            event.resolved_at = now
            _enqueue(db, event, "resolved", now)
    db.commit()


def send_feishu(app_id: str, secret: str, chat_id: str, message: str,
                receive_id_type: str = "chat_id") -> None:
    with httpx.Client(timeout=6) as client:
        token_response = client.post(
            f"{FEISHU_API}/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": secret},
        )
        token_response.raise_for_status()
        token_data = token_response.json()
        if token_data.get("code") != 0 or not token_data.get("tenant_access_token"):
            raise ValueError(f"飞书获取租户令牌失败（code={token_data.get('code')}）")
        if not chat_id and receive_id_type == "chat_id":
            chats_response = client.get(
                f"{FEISHU_API}/im/v1/chats",
                params={"page_size": 2},
                headers={"Authorization": f"Bearer {token_data['tenant_access_token']}"},
            )
            chats_response.raise_for_status()
            chats = chats_response.json()
            if chats.get("code") != 0:
                raise ValueError("无法获取机器人所在群，请检查群信息读取权限或填写群聊 ID。")
            data = chats.get("data", {})
            items = data.get("items", [])
            if not items:
                raise ValueError("机器人尚未加入群聊，请先将机器人加入接收告警的群。")
            if len(items) != 1 or data.get("has_more"):
                raise ValueError("机器人加入了多个群聊，请填写目标群聊 ID。")
            chat_id = items[0]["chat_id"]
        response = client.post(
            f"{FEISHU_API}/im/v1/messages",
            params={"receive_id_type": receive_id_type},
            headers={"Authorization": f"Bearer {token_data['tenant_access_token']}"},
            json={
                "receive_id": chat_id, "msg_type": "text",
                "content": json.dumps({"text": message}, ensure_ascii=False),
            },
        )
        response.raise_for_status()
        result = response.json()
        if result.get("code") != 0:
            raise ValueError(f"飞书发送消息失败（code={result.get('code')}）")


def deliver_alerts(db: Session, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    config = db.get(FeishuSettings, 1)
    if not config or not config.enabled:
        db.rollback()
        return
    try:
        secret = _cipher().decrypt(config.app_secret_ciphertext.encode()).decode()
    except (InvalidToken, UnicodeDecodeError, HTTPException):
        logger.error("飞书应用密钥无法解密，请检查服务端加密主密钥")
        db.rollback()
        return
    app_id = config.app_id
    db.rollback()
    for _ in range(10):
        # Claim one delivery and release the database lock before network I/O.
        # An expired claim is retried after a worker crash.
        if db.bind.dialect.name == "postgresql" and not db.scalar(
            select(func.pg_try_advisory_xact_lock(7201925))
        ):
            db.rollback()
            return
        item = db.scalar(select(AlertDelivery).where(
            AlertDelivery.status.in_(("pending", "sending")),
            AlertDelivery.next_attempt_at <= now,
        ).order_by(AlertDelivery.id).limit(1))
        if item is None:
            db.rollback()
            return
        event = db.get(AlertEvent, item.event_id)
        rule = db.get(AlertRule, event.rule_id) if event else None
        if not rule:
            item.status = "failed"
            item.last_error = "告警规则不存在"
            db.commit()
            continue
        message = (
            f"AI Gateway 告警{'恢复' if item.kind == 'resolved' else '触发'}\n"
            f"级别：{rule.level}\n规则：{rule.name}\n指标：{rule.metric}\n"
            f"对象 ID：{rule.scope_id or '平台'}\n当前值：{item.current_value}%\n"
            f"阈值：{event.threshold}%\n事件 ID：{event.id}\n"
            f"时间：{now.strftime('%Y-%m-%d %H:%M UTC')}"
        )
        delivery_id = item.id
        target_id, target_type = item.receive_id, item.receive_id_type
        item.status = "sending"
        item.next_attempt_at = now + timedelta(minutes=2)
        db.commit()
        try:
            send_feishu(app_id, secret, target_id, message, target_type)
        except (httpx.HTTPError, ValueError) as exc:
            item = db.get(AlertDelivery, delivery_id)
            item.attempts += 1
            item.status = "failed" if item.attempts >= 5 else "pending"
            item.next_attempt_at = now + timedelta(minutes=min(2 ** item.attempts, 60))
            # Never persist transport errors containing credentials or response bodies.
            item.last_error = (
                type(exc).__name__ if isinstance(exc, httpx.HTTPError) else str(exc)[:255]
            )
            logger.warning("飞书告警投递失败，事件 %s：%s", event.id, item.last_error)
        else:
            item = db.get(AlertDelivery, delivery_id)
            item.attempts += 1
            item.status = "sent"
            item.sent_at = now
            item.last_error = None
        db.commit()


async def alert_worker() -> None:
    while True:
        try:
            def tick() -> None:
                with SessionLocal() as db:
                    evaluate_alerts(db)
                with SessionLocal() as db:
                    deliver_alerts(db)
            await asyncio.to_thread(tick)
        except Exception:
            logger.exception("告警任务运行失败")
        await asyncio.sleep(60)


@router.get("/settings/feishu")
def get_feishu(db: Session = Depends(get_db), user: User = Depends(actor)) -> dict:
    require_platform(user)
    item = db.get(FeishuSettings, 1)
    return success_response({
        "app_id": item.app_id if item else "",
        "chat_id": item.chat_id if item else "",
        "enabled": item.enabled if item else False,
        "has_secret": bool(item and item.app_secret_ciphertext),
    }).model_dump(mode="json")


@router.put("/settings/feishu")
def put_feishu(payload: FeishuPayload, db: Session = Depends(get_db),
               user: User = Depends(actor)) -> dict:
    require_platform(user)
    item = db.get(FeishuSettings, 1)
    if item is None and not payload.app_secret:
        raise HTTPException(422, "首次配置时必须填写应用密钥。")
    encrypted = (
        _cipher().encrypt(payload.app_secret.encode()).decode() if payload.app_secret else None
    )
    if item is None:
        item = FeishuSettings(id=1, app_secret_ciphertext=encrypted)
        db.add(item)
    elif encrypted:
        item.app_secret_ciphertext = encrypted
    item.app_id = payload.app_id.strip()
    item.chat_id = payload.chat_id.strip()
    item.enabled = payload.enabled
    db.commit()
    return get_feishu(db, user)


@router.post("/settings/feishu/test")
def test_feishu(db: Session = Depends(get_db), user: User = Depends(actor)) -> dict:
    require_platform(user)
    item = db.get(FeishuSettings, 1)
    if not item:
        raise HTTPException(422, "请先保存飞书设置。")
    try:
        secret = _cipher().decrypt(item.app_secret_ciphertext.encode()).decode()
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise HTTPException(503, "飞书密钥无法解密。") from exc
    try:
        send_feishu(item.app_id, secret, item.chat_id, "AI Gateway 告警中心：飞书消息测试成功。")
    except ValueError as exc:
        raise HTTPException(502, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, "飞书发送失败，请检查应用权限与群聊 ID。") from exc
    return success_response({"sent": True}).model_dump()


@router.get("/rules")
def list_rules(filters: str | None = Query(None, max_length=4096),
               db: Session = Depends(get_db), user: User = Depends(actor)) -> dict:
    require_platform(user)
    query = select(AlertRule)
    expression = filter_expression(filters, _filter_columns())
    if expression is not None:
        query = query.where(expression)
    return success_response([_rule_data(r) for r in db.scalars(
        query.order_by(AlertRule.id.desc()))]).model_dump(mode="json")


@router.post("/rules/{rule_id}/test")
def test_rule_push(rule_id: int, db: Session = Depends(get_db),
                   user: User = Depends(actor)) -> dict:
    require_platform(user)
    rule = db.get(AlertRule, rule_id)
    if not rule:
        raise HTTPException(404, "告警规则不存在。")
    config = db.get(FeishuSettings, 1)
    if not config:
        raise HTTPException(422, "请先保存飞书应用设置。")
    try:
        secret = _cipher().decrypt(config.app_secret_ciphertext.encode()).decode()
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise HTTPException(503, "飞书密钥无法解密。") from exc
    app_id = config.app_id
    targets = [dict(target) for target in _recipients(db, rule)]
    message = (f"AI Gateway 告警中心：测试推送\n规则：{rule.name}\n"
               f"指标：{rule.metric}\n阈值：{rule.threshold}%\n"
               "此消息用于验证通知配置，不代表实际告警。")
    db.rollback()

    def push(target: dict) -> dict:
        try:
            send_feishu(app_id, secret, target["receive_id"], message,
                        target["receive_id_type"])
        except ValueError as exc:
            return {**target, "sent": False, "error": str(exc)[:255]}
        except httpx.HTTPError:
            return {**target, "sent": False, "error": "飞书请求失败，请检查网络和应用权限。"}
        return {**target, "sent": True, "error": None}

    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(push, targets))
    return success_response({"results": results}).model_dump(mode="json")


def _filter_columns(events: bool = False) -> dict:
    columns = {
        "rule_name": (AlertRule.name, "text"),
        "metric": (AlertRule.metric, "select",
                   {"error_rate", "key_token_usage", "project_amount_usage"}),
        "level": (AlertRule.level, "select", {"warning", "critical"}),
        "scope_type": (case((AlertRule.scope_id.is_(None), "platform"),
                            (AlertRule.metric == "key_token_usage", "key"),
                            else_="project"), "select", {"platform", "project", "key"}),
        "scope_id": (AlertRule.scope_id, "number"),
    }
    if events:
        columns.update({
            "id": (AlertEvent.id, "number"),
            "status": (AlertEvent.status, "select", {"open", "acknowledged", "resolved"}),
            "threshold": (AlertEvent.threshold, "decimal"),
            "current_value": (AlertEvent.current_value, "decimal"),
            "triggered_at": (AlertEvent.triggered_at, "date"),
            "acknowledged_at": (AlertEvent.acknowledged_at, "date"),
            "resolved_at": (AlertEvent.resolved_at, "date"),
        })
    else:
        columns.update({
            "id": (AlertRule.id, "number"),
            "enabled": (AlertRule.enabled, "boolean", {"0", "1"}),
            "threshold": (AlertRule.threshold, "decimal"),
            "window_minutes": (AlertRule.window_minutes, "number"),
            "min_samples": (AlertRule.min_samples, "number"),
            "created_at": (AlertRule.created_at, "date"),
        })
    return columns


@router.post("/rules", status_code=201)
def create_rule(payload: RulePayload, db: Session = Depends(get_db),
                user: User = Depends(actor)) -> dict:
    require_platform(user)
    _validate_scope(db, payload)
    rule = AlertRule(**payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return success_response(_rule_data(rule)).model_dump(mode="json")


@router.patch("/rules/{rule_id}")
def update_rule(rule_id: int, payload: RulePayload, db: Session = Depends(get_db),
                user: User = Depends(actor)) -> dict:
    require_platform(user)
    rule = db.get(AlertRule, rule_id)
    if not rule:
        raise HTTPException(404, "告警规则不存在。")
    if db.scalar(select(AlertEvent.id).where(
        AlertEvent.rule_id == rule_id, AlertEvent.status.in_(ACTIVE),
    )) and (rule.metric != payload.metric or rule.scope_id != payload.scope_id):
        raise HTTPException(409, "请先恢复或关闭该规则的未结束事件。")
    _validate_scope(db, payload)
    for key, value in payload.model_dump().items():
        setattr(rule, key, value)
    db.commit()
    return success_response(_rule_data(rule)).model_dump(mode="json")


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db),
                user: User = Depends(actor)) -> dict:
    require_platform(user)
    rule = db.get(AlertRule, rule_id)
    if not rule:
        raise HTTPException(404, "告警规则不存在。")
    if db.scalar(select(AlertEvent.id).where(AlertEvent.rule_id == rule_id)):
        raise HTTPException(409, "已有告警事件的规则不能删除，请停用。")
    db.delete(rule)
    db.commit()
    return success_response({"deleted": True}).model_dump()


@router.get("/events")
def list_events(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                status: Literal["open", "acknowledged", "resolved"] | None = None,
                filters: str | None = Query(None, max_length=4096),
                db: Session = Depends(get_db), user: User = Depends(actor)) -> dict:
    require_platform(user)
    query = select(AlertEvent, AlertRule).join(AlertRule, AlertRule.id == AlertEvent.rule_id)
    if status:
        query = query.where(AlertEvent.status == status)
    expression = filter_expression(filters, _filter_columns(events=True))
    if expression is not None:
        query = query.where(expression)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(query.order_by(AlertEvent.id.desc()).offset(
        (page - 1) * page_size).limit(page_size)).all()
    return success_response({
        "items": [_event_data(event, rule) for event, rule in rows],
        "total": total, "page": page, "page_size": page_size,
    }).model_dump(mode="json")


@router.get("/events/{event_id}/deliveries")
def event_deliveries(event_id: int, db: Session = Depends(get_db),
                     user: User = Depends(actor)) -> dict:
    require_platform(user)
    if not db.get(AlertEvent, event_id):
        raise HTTPException(404, "告警事件不存在。")
    return success_response([{
        "kind": d.kind, "current_value": d.current_value, "status": d.status,
        "id": d.id, "receive_id_type": d.receive_id_type, "receive_id": d.receive_id,
        "attempts": d.attempts,
        "last_error": d.last_error, "sent_at": d.sent_at,
    } for d in db.scalars(select(AlertDelivery).where(
        AlertDelivery.event_id == event_id).order_by(AlertDelivery.id))]).model_dump(mode="json")


@router.post("/events/{event_id}/ack")
def acknowledge(event_id: int, db: Session = Depends(get_db),
                user: User = Depends(actor)) -> dict:
    require_platform(user)
    event = db.get(AlertEvent, event_id)
    if not event:
        raise HTTPException(404, "告警事件不存在。")
    if event.status != "open":
        raise HTTPException(409, "仅未确认事件可确认。")
    event.status = "acknowledged"
    event.acknowledged_at = datetime.now(UTC)
    event.acknowledged_by = user.id
    db.commit()
    return success_response(
        _event_data(event, db.get(AlertRule, event.rule_id))
    ).model_dump(mode="json")


@router.post("/events/{event_id}/resolve")
def resolve(event_id: int, db: Session = Depends(get_db),
            user: User = Depends(actor)) -> dict:
    require_platform(user)
    event = db.get(AlertEvent, event_id)
    if not event:
        raise HTTPException(404, "告警事件不存在。")
    if event.status not in ACTIVE:
        raise HTTPException(409, "事件已经恢复。")
    event.status = "resolved"
    event.resolved_at = datetime.now(UTC)
    rule = db.get(AlertRule, event.rule_id)
    rule.suppressed_until_recovery = True
    _enqueue(db, event, "resolved", event.resolved_at)
    db.commit()
    return success_response(
        _event_data(event, rule)
    ).model_dump(mode="json")
