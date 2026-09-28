from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.demo_data import get_overview_summary_data
from app.db.models import (
    ApiKey,
    ModelNode,
    Organization,
    Project,
    Provider,
    ProviderModel,
    RequestLog,
    UsageRecord,
)
from app.modules.overview.schemas import (
    OverviewActivity,
    OverviewDay,
    OverviewFailure,
    OverviewModel,
    OverviewSummary,
)


def _count_rows(db: Session, model, *filters) -> int:
    statement = select(func.count()).select_from(model)
    for condition in filters:
        statement = statement.where(condition)
    return int(db.scalar(statement) or 0)


def get_overview_summary(db: Session) -> OverviewSummary:
    summary = OverviewSummary()

    try:
        summary.total_requests = _count_rows(db, RequestLog)
        summary.total_tokens = int(
            db.scalar(select(func.coalesce(func.sum(UsageRecord.total_tokens), 0))) or 0
        )
        summary.total_cost = Decimal(
            db.scalar(select(func.coalesce(func.sum(UsageRecord.estimated_cost), 0))) or "0"
        )
        summary.organization_count = _count_rows(
            db, Organization, Organization.deleted_at.is_(None),
        )
        summary.project_count = _count_rows(db, Project, Project.deleted_at.is_(None))
        summary.key_count = _count_rows(db, ApiKey, ApiKey.deleted_at.is_(None))
        summary.provider_count = _count_rows(db, Provider)
        summary.model_count = _count_rows(db, ProviderModel)
        summary.node_count = _count_rows(db, ModelNode)
        summary.active_node_count = _count_rows(db, ModelNode, ModelNode.status == 1)
        summary.healthy_provider_count = _count_rows(
            db, Provider, Provider.health_status == "healthy"
        )
        summary.data_source = "database"
        summary.database_status = "connected"
        summary.status_message = "已连接数据库，返回实时平台汇总。"
    except SQLAlchemyError:
        bootstrap_data = get_overview_summary_data()
        for key, value in bootstrap_data.items():
            setattr(summary, key, value)
        summary.data_source = "bootstrap"
        summary.database_status = "unavailable"
        summary.status_message = "数据库暂不可用，当前返回内置演示数据，方便继续联调前后端。"

    return summary


def get_overview_activity(
    db: Session, days: int, now: datetime | None = None,
) -> OverviewActivity:
    today = (now or datetime.now(UTC)).date()
    start = today - timedelta(days=days - 1)
    end = today + timedelta(days=1)
    # Gateway log timestamps are stored as naive UTC; use a half-open UTC window.
    start_at = datetime.combine(start, datetime.min.time())
    end_at = datetime.combine(end, datetime.min.time())
    success = case((RequestLog.http_status.between(200, 299), 1), else_=0)
    log_day = func.date(RequestLog.created_at)

    daily_rows = db.execute(
        select(
            log_day.label("day"),
            func.count(RequestLog.id),
            func.sum(success),
            func.coalesce(func.sum(UsageRecord.total_tokens), 0),
        )
        .outerjoin(UsageRecord, UsageRecord.request_log_id == RequestLog.id)
        .where(RequestLog.created_at >= start_at, RequestLog.created_at < end_at)
        .group_by(log_day)
    ).all()
    by_date = {
        str(day): OverviewDay(
            date=str(day), requests=int(requests), successes=int(successes or 0),
            tokens=int(tokens),
        )
        for day, requests, successes, tokens in daily_rows
    }
    daily = [
        by_date.get(day.isoformat(), OverviewDay(date=day.isoformat()))
        for day in (start + timedelta(days=index) for index in range(days))
    ]
    top_rows = db.execute(
        select(RequestLog.public_model_name, func.count(RequestLog.id).label("requests"))
        .where(RequestLog.created_at >= start_at, RequestLog.created_at < end_at)
        .group_by(RequestLog.public_model_name)
        .order_by(func.count(RequestLog.id).desc(), RequestLog.public_model_name)
        .limit(5)
    ).all()
    failures = db.scalars(
        select(RequestLog)
        .where(
            RequestLog.created_at >= start_at, RequestLog.created_at < end_at,
            ~RequestLog.http_status.between(200, 299),
        )
        .order_by(RequestLog.created_at.desc(), RequestLog.id.desc())
        .limit(5)
    ).all()
    return OverviewActivity(
        days=days,
        total_requests=sum(item.requests for item in daily),
        successful_requests=sum(item.successes for item in daily),
        total_tokens=sum(item.tokens for item in daily),
        daily=daily,
        top_models=[OverviewModel(name=name, requests=count) for name, count in top_rows],
        recent_failures=[
            OverviewFailure(
                request_id=item.request_id, model=item.public_model_name,
                http_status=item.http_status, created_at=item.created_at,
            )
            for item in failures
        ],
    )
