from decimal import Decimal

from sqlalchemy import func, select
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
from app.modules.overview.schemas import OverviewSummary


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
        summary.organization_count = _count_rows(db, Organization, Organization.deleted_at.is_(None))
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
