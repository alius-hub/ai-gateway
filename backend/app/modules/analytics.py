"""Admin analytics from request logs and their optional usage records."""

# ruff: noqa: B008
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.responses import success_response
from app.db.models import (
    ApiKey,
    Organization,
    Project,
    Provider,
    ProviderModel,
    RequestLog,
    UsageRecord,
    User,
)
from app.db.session import get_db
from app.modules.identity.router import actor, require_platform

router = APIRouter(prefix="/analytics", tags=["分析看板"])
Dimension = Literal[
    "organization", "project", "key", "public_model", "access_model",
    "provider", "endpoint", "model_type",
]
USAGE_DIMENSIONS = ("organization", "project", "key", "public_model", "access_model")
COST_DIMENSIONS = ("organization", "project", "provider", "access_model")
PERFORMANCE_DIMENSIONS = ("provider", "access_model", "endpoint", "model_type")

DIMENSIONS = {
    "organization": (RequestLog.organization_id, Organization, Organization.name),
    "project": (RequestLog.project_id, Project, Project.name),
    "key": (RequestLog.api_key_id, ApiKey, ApiKey.name),
    "public_model": (RequestLog.public_model_name, None, None),
    "access_model": (RequestLog.provider_model_id, ProviderModel, ProviderModel.access_model_code),
    "provider": (RequestLog.provider_id, Provider, Provider.name),
    "endpoint": (RequestLog.endpoint, None, None),
    "model_type": (RequestLog.model_type, None, None),
}


def window(start: date | None, end: date | None) -> tuple[date, date, datetime, datetime]:
    last = end or datetime.now(UTC).date()
    first = start or last - timedelta(days=6)
    if first > last or (last - first).days >= 90:
        raise HTTPException(422, "日期范围须为 1 至 90 天")
    return first, last, datetime.combine(first, time.min), datetime.combine(
        last + timedelta(days=1), time.min,
    )


def conditions(begin: datetime, finish: datetime, scope: Dimension | None, value: str | None):
    result = [RequestLog.created_at >= begin, RequestLog.created_at < finish]
    if bool(scope) != bool(value):
        raise HTTPException(422, "筛选维度和值必须同时提供")
    if scope:
        column, model, _ = DIMENSIONS[scope]
        if model:
            if value == "none":
                result.append(column.is_(None))
            else:
                try:
                    identifier = int(value)
                    if identifier <= 0:
                        raise ValueError
                except ValueError as exc:
                    raise HTTPException(422, "维度 ID 必须为正整数") from exc
                result.append(column == identifier)
        else:
            result.append(column == value)
    return result


def group_query(dimension: Dimension, *columns):
    group, model, name = DIMENSIONS[dimension]
    statement = select(group.label("value"), (
        func.coalesce(name, "已删除") if model else group
    ).label("label"), *columns).select_from(RequestLog).outerjoin(
        UsageRecord, UsageRecord.request_log_id == RequestLog.id,
    )
    if model:
        statement = statement.outerjoin(model, model.id == group)
    return statement.group_by(group, name) if model else statement.group_by(group)


def identity(value, label) -> dict:
    return {"value": str(value) if value is not None else "none",
            "label": str(label) if value is not None else "未归属"}


def calendar(first: date, last: date, rows: dict, empty):
    return [
        {"date": (first + timedelta(days=offset)).isoformat(),
         **rows.get((first + timedelta(days=offset)).isoformat(), empty)}
        for offset in range((last - first).days + 1)
    ]


def usage(db: Session, first: date, last: date, filters: list, dimension: Dimension) -> dict:
    success = case((RequestLog.http_status.between(200, 299), 1), else_=0)
    day = func.date(RequestLog.created_at)
    measures = (
        func.count(RequestLog.id), func.sum(success),
        func.coalesce(func.sum(UsageRecord.input_tokens), 0),
        func.coalesce(func.sum(UsageRecord.output_tokens), 0),
        func.coalesce(func.sum(UsageRecord.total_tokens), 0),
    )
    daily_rows = db.execute(
        select(day, *measures).select_from(RequestLog).outerjoin(
            UsageRecord, UsageRecord.request_log_id == RequestLog.id,
        ).where(*filters).group_by(day)
    ).all()
    data = {
        str(day_value): dict(zip(
            ("requests", "successes", "input_tokens", "output_tokens", "total_tokens"),
            (int(x or 0) for x in values),
            strict=True,
        ))
        for day_value, *values in daily_rows
    }
    daily = calendar(first, last, data, dict(
        requests=0, successes=0, input_tokens=0, output_tokens=0, total_tokens=0,
    ))
    ranking = db.execute(
        group_query(dimension, *measures).where(*filters)
        .order_by(func.count(RequestLog.id).desc()).limit(10)
    ).all()
    return {
        "start_date": first.isoformat(), "end_date": last.isoformat(),
        "dimension": dimension,
        "summary": {key: sum(item[key] for item in daily)
                    for key in ("requests", "successes", "input_tokens",
                                "output_tokens", "total_tokens")},
        "daily": daily,
        "ranking": [{**identity(value, label), **dict(zip(
            ("requests", "successes", "input_tokens", "output_tokens", "total_tokens"),
            (int(x or 0) for x in values),
            strict=True,
        ))} for value, label, *values in ranking],
    }


@router.get("/usage")
async def usage_endpoint(
    start_date: date | None = None, end_date: date | None = None,
    dimension: Literal["organization", "project", "key", "public_model", "access_model"]
    = "public_model",
    scope: Dimension | None = None, value: str | None = Query(None, max_length=128),
    db: Session = Depends(get_db), user: User = Depends(actor),
) -> dict:
    require_platform(user)
    first, last, begin, finish = window(start_date, end_date)
    return success_response(usage(
        db, first, last, conditions(begin, finish, scope, value), dimension,
    )).model_dump()


def cost(db: Session, first: date, last: date, filters: list,
         dimension: Dimension, currency: str) -> dict:
    day = func.date(RequestLog.created_at)
    priced = [*filters, UsageRecord.currency == currency,
              UsageRecord.estimated_cost.is_not(None)]
    daily_rows = db.execute(
        select(day, func.count(UsageRecord.id), func.sum(UsageRecord.estimated_cost))
        .select_from(RequestLog).join(UsageRecord, UsageRecord.request_log_id == RequestLog.id)
        .where(*priced).group_by(day)
    ).all()
    data = {str(d): {"priced_requests": int(n), "estimated_cost": str(total)}
            for d, n, total in daily_rows}
    daily = calendar(first, last, data, {"priced_requests": 0, "estimated_cost": "0"})
    ranking = db.execute(
        group_query(dimension, func.count(UsageRecord.id),
                    func.sum(UsageRecord.estimated_cost)).where(*priced)
        .order_by(func.sum(UsageRecord.estimated_cost).desc()).limit(10)
    ).all()
    records = db.execute(
        select(func.count(RequestLog.id), func.count(UsageRecord.id))
        .select_from(RequestLog).outerjoin(
            UsageRecord, (UsageRecord.request_log_id == RequestLog.id)
            & (UsageRecord.currency == currency)
            & UsageRecord.estimated_cost.is_not(None),
        ).where(*filters)
    ).one()
    priced_count = sum(item["priced_requests"] for item in daily)
    total_cost = sum((Decimal(item["estimated_cost"]) for item in daily), Decimal("0"))
    return {
        "start_date": first.isoformat(), "end_date": last.isoformat(),
        "currency": currency, "dimension": dimension,
        "summary": {
            "requests": int(records[0]), "priced_requests": priced_count,
            "unpriced_requests": int(records[0]) - int(records[1]),
            "estimated_cost": str(total_cost),
            "average_cost": str(total_cost / priced_count) if priced_count else None,
        },
        "daily": daily,
        "ranking": [{**identity(value, label), "priced_requests": int(n),
                     "estimated_cost": str(total)}
                    for value, label, n, total in ranking],
    }


@router.get("/cost")
async def cost_endpoint(
    start_date: date | None = None, end_date: date | None = None,
    dimension: Literal["organization", "project", "provider", "access_model"] = "provider",
    currency: str = Query("CNY", min_length=3, max_length=16),
    scope: Dimension | None = None, value: str | None = Query(None, max_length=128),
    db: Session = Depends(get_db), user: User = Depends(actor),
) -> dict:
    require_platform(user)
    first, last, begin, finish = window(start_date, end_date)
    return success_response(cost(
        db, first, last, conditions(begin, finish, scope, value), dimension, currency,
    )).model_dump()


@router.get("/currencies")
async def currencies(db: Session = Depends(get_db), user: User = Depends(actor)) -> dict:
    require_platform(user)
    names = db.scalars(select(UsageRecord.currency).where(
        UsageRecord.estimated_cost.is_not(None),
    ).distinct().order_by(UsageRecord.currency)).all()
    return success_response(sorted(set(names) | {"CNY"})).model_dump()


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    point = (len(ordered) - 1) * fraction
    lower = int(point)
    return round(ordered[lower] + (ordered[min(lower + 1, len(ordered) - 1)]
                                   - ordered[lower]) * (point - lower), 2)


def percentiles(db: Session, filters: list, group=None, value=None) -> tuple:
    where = [*filters, RequestLog.latency_ms.is_not(None)]
    if group is not None:
        where.append(group.is_(None) if value is None else group == value)
    if db.bind.dialect.name == "postgresql":
        return db.execute(select(
            func.percentile_cont(0.95).within_group(RequestLog.latency_ms),
            func.percentile_cont(0.99).within_group(RequestLog.latency_ms),
        ).where(*where)).one()
    samples = list(db.scalars(select(RequestLog.latency_ms).where(*where)))
    return percentile(samples, 0.95), percentile(samples, 0.99)


def performance(db: Session, first: date, last: date, filters: list,
                dimension: Dimension) -> dict:
    day = func.date(RequestLog.created_at)
    success = case((RequestLog.http_status.between(200, 299), 1), else_=0)
    speed = case((
        (RequestLog.ttft_ms.is_not(None))
        & (RequestLog.latency_ms > RequestLog.ttft_ms)
        & (UsageRecord.output_tokens > 0),
        1000.0 * UsageRecord.output_tokens / (RequestLog.latency_ms - RequestLog.ttft_ms),
    ), else_=None)
    metrics = (
        func.count(RequestLog.id), func.sum(success),
        func.count(RequestLog.latency_ms), func.avg(RequestLog.latency_ms),
        func.count(RequestLog.ttft_ms), func.avg(RequestLog.ttft_ms),
        func.count(RequestLog.tpot_ms), func.avg(RequestLog.tpot_ms),
        func.count(speed), func.avg(speed),
    )
    rows = db.execute(select(day, *metrics).select_from(RequestLog).outerjoin(
        UsageRecord, UsageRecord.request_log_id == RequestLog.id,
    ).where(*filters).group_by(day)).all()
    daily = calendar(first, last, {
        str(d): {
            "requests": int(n), "successes": int(ok or 0),
            "latency_samples": int(ns), "avg_latency_ms": round(float(avg), 2) if avg else None,
            "ttft_samples": int(ts), "avg_ttft_ms": round(float(ttft), 2) if ttft else None,
            "tpot_samples": int(ps), "avg_tpot_ms": round(float(tpot), 2) if tpot else None,
            "speed_samples": int(ss),
            "avg_tokens_per_second": round(float(mean_speed), 2) if mean_speed else None,
        }
        for d, n, ok, ns, avg, ts, ttft, ps, tpot, ss, mean_speed in rows
    }, {"requests": 0, "successes": 0, "latency_samples": 0,
        "avg_latency_ms": None, "ttft_samples": 0, "avg_ttft_ms": None,
        "tpot_samples": 0, "avg_tpot_ms": None,
        "speed_samples": 0, "avg_tokens_per_second": None})
    if db.bind.dialect.name == "postgresql":
        daily_percentiles = {
            str(d): (float(p95), float(p99))
            for d, p95, p99 in db.execute(select(
                day,
                func.percentile_cont(0.95).within_group(RequestLog.latency_ms),
                func.percentile_cont(0.99).within_group(RequestLog.latency_ms),
            ).where(*filters, RequestLog.latency_ms.is_not(None)).group_by(day))
        }
    else:
        daily_percentiles = {
            item["date"]: percentiles(
                db, [*filters, RequestLog.created_at >= datetime.combine(
                    date.fromisoformat(item["date"]), time.min,
                ), RequestLog.created_at < datetime.combine(
                    date.fromisoformat(item["date"]) + timedelta(days=1), time.min,
                )],
            )
            for item in daily if item["latency_samples"]
        }
    for item in daily:
        item["p95_latency_ms"], item["p99_latency_ms"] = daily_percentiles.get(
            item["date"], (None, None),
        )
    total = db.execute(select(*metrics).select_from(RequestLog).outerjoin(
        UsageRecord, UsageRecord.request_log_id == RequestLog.id,
    ).where(*filters)).one()
    n, ok, ns, avg, ts, ttft, ps, tpot, ss, mean_speed = total
    p95, p99 = percentiles(db, filters)
    rank_rows = db.execute(
        group_query(dimension, *metrics).where(*filters)
        .order_by(func.count(RequestLog.id).desc()).limit(10)
    ).all()
    group = DIMENSIONS[dimension][0]
    ranking = []
    for (value, label, count, good, samples, mean, tcount, tmean,
         pcount, pmean, speed_count, speed_mean) in rank_rows:
        p95_rank, p99_rank = percentiles(db, filters, group, value)
        ranking.append({
            **identity(value, label), "requests": int(count), "successes": int(good or 0),
            "latency_samples": int(samples),
            "avg_latency_ms": round(float(mean), 2) if mean is not None else None,
            "p95_latency_ms": float(p95_rank) if p95_rank is not None else None,
            "p99_latency_ms": float(p99_rank) if p99_rank is not None else None,
            "ttft_samples": int(tcount),
            "avg_ttft_ms": round(float(tmean), 2) if tmean is not None else None,
            "tpot_samples": int(pcount),
            "avg_tpot_ms": round(float(pmean), 2) if pmean is not None else None,
            "speed_samples": int(speed_count),
            "avg_tokens_per_second": (
                round(float(speed_mean), 2) if speed_mean is not None else None
            ),
        })
    errors = db.execute(select(
        RequestLog.error_code, RequestLog.http_status, func.count(RequestLog.id),
    ).where(*filters, ~RequestLog.http_status.between(200, 299))
        .group_by(RequestLog.error_code, RequestLog.http_status)
        .order_by(func.count(RequestLog.id).desc()).limit(10)).all()
    return {
        "start_date": first.isoformat(), "end_date": last.isoformat(),
        "dimension": dimension,
        "summary": {
            "requests": int(n), "successes": int(ok or 0), "latency_samples": int(ns),
            "avg_latency_ms": round(float(avg), 2) if avg is not None else None,
            "p95_latency_ms": float(p95) if p95 is not None else None,
            "p99_latency_ms": float(p99) if p99 is not None else None,
            "ttft_samples": int(ts),
            "avg_ttft_ms": round(float(ttft), 2) if ttft is not None else None,
            "tpot_samples": int(ps),
            "avg_tpot_ms": round(float(tpot), 2) if tpot is not None else None,
            "speed_samples": int(ss),
            "avg_tokens_per_second": round(float(mean_speed), 2)
            if mean_speed is not None else None,
        },
        "daily": daily, "ranking": ranking,
        "errors": [{"code": code or f"HTTP {status}", "http_status": status,
                    "requests": count} for code, status, count in errors],
    }


@router.get("/performance")
async def performance_endpoint(
    start_date: date | None = None, end_date: date | None = None,
    dimension: Literal["provider", "access_model", "endpoint", "model_type"] = "access_model",
    scope: Dimension | None = None, value: str | None = Query(None, max_length=128),
    db: Session = Depends(get_db), user: User = Depends(actor),
) -> dict:
    require_platform(user)
    first, last, begin, finish = window(start_date, end_date)
    return success_response(performance(
        db, first, last, conditions(begin, finish, scope, value), dimension,
    )).model_dump()
