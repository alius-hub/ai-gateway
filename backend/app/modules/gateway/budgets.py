"""Durable, incrementally maintained CNY spend (updated with the usage transaction)."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models import ApiKey, GatewaySpend, Project
from app.modules.gateway.limits import period


def baselines(db: Session, key: ApiKey, project: Project | None) -> tuple[int, int]:
    def get(scope: str, scope_id: int, kind: str, stamp: str) -> int:
        row = db.get(GatewaySpend, (scope, scope_id, kind, stamp))
        return row.spent_cents if row else 0

    stamp, _ = period(datetime.now(UTC), key.budget_period)
    return (
        get("key", key.id, key.budget_period, stamp) if key.amount_budget is not None else 0,
        get("project", project.id, "all", "all")
        if project is not None and project.amount_budget is not None else 0,
    )


def increment(db: Session, key: ApiKey, cents: int, now: datetime) -> None:
    if not cents:
        return
    # PostgreSQL in production, SQLite for isolated tests. Upserts prevent lost updates.
    if db.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert

    buckets = [("key", key.id, kind, period(now, kind)[0]) for kind in ("week", "month")]
    if key.project_id is not None:
        buckets.append(("project", key.project_id, "all", "all"))
    for scope, scope_id, kind, stamp in sorted(buckets):
        statement = insert(GatewaySpend).values(
            scope=scope, scope_id=scope_id, period_kind=kind, period_stamp=stamp,
            spent_cents=cents,
        )
        db.execute(statement.on_conflict_do_update(
            index_elements=["scope", "scope_id", "period_kind", "period_stamp"],
            set_={"spent_cents": GatewaySpend.spent_cents + cents},
        ))
