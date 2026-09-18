from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.exc import SQLAlchemyError

from app.core.demo_data import (
    AGGREGATED_MODELS,
    AGGREGATE_MODEL_NODE_BINDINGS,
    API_KEYS,
    MODEL_NODES,
    ORGANIZATIONS,
    PROJECTS,
    PROJECT_MODEL_POLICIES,
    PROVIDER_MODELS,
    PROVIDERS,
    REQUEST_LOGS,
    USAGE_RECORDS,
    USERS,
)
from app.db.models import (
    AggregateModelNodeBinding,
    AggregatedModel,
    ApiKey,
    ModelNode,
    Organization,
    Project,
    ProjectModelPolicy,
    Provider,
    ProviderModel,
    RequestLog,
    UsageRecord,
    User,
)
from app.db.session import SessionLocal


INSERT_ORDER = [
    (User, USERS),
    (Organization, ORGANIZATIONS),
    (Project, PROJECTS),
    (Provider, PROVIDERS),
    (AggregatedModel, AGGREGATED_MODELS),
    (ApiKey, API_KEYS),
    (ProviderModel, PROVIDER_MODELS),
    (ModelNode, MODEL_NODES),
    (AggregateModelNodeBinding, AGGREGATE_MODEL_NODE_BINDINGS),
    (ProjectModelPolicy, PROJECT_MODEL_POLICIES),
    (RequestLog, REQUEST_LOGS),
    (UsageRecord, USAGE_RECORDS),
]


def seed() -> None:
    session = SessionLocal()
    try:
        for model, _ in reversed(INSERT_ORDER):
            session.execute(delete(model))

        for model, rows in INSERT_ORDER:
            session.bulk_insert_mappings(model, rows)

        session.commit()
        print("Seeded demo data successfully.")
    except SQLAlchemyError as exc:
        session.rollback()
        raise SystemExit(f"Seed failed: {exc}") from exc
    finally:
        session.close()


if __name__ == "__main__":
    seed()
