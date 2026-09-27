from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.responses import success_response
from app.db.models import RoutingWorkflow, User
from app.db.session import get_db
from app.modules.identity.router import actor
from app.modules.routing.strategies import BUILTIN_STRATEGIES
from app.modules.routing.workflow import (
    Definition, SimulationPayload, simulate, validate_bindings,
)

router = APIRouter(prefix="/routing", tags=["路由流程"])


@router.get("/strategies")
def list_strategies(_user: User = Depends(actor)) -> dict:
    return success_response({"items": list(BUILTIN_STRATEGIES)}).model_dump()


def serialize(item: RoutingWorkflow) -> dict:
    return {
        "id": item.id, "name": item.name, "description": item.description,
        "model_type": item.model_type, "definition": item.definition,
    }


def get_workflow(db: Session, workflow_id: int) -> RoutingWorkflow:
    item = db.get(RoutingWorkflow, workflow_id)
    if item is None:
        raise HTTPException(404, "路由流程不存在。")
    return item


@router.get("/workflows")
def list_workflows(db: Session = Depends(get_db), _user: User = Depends(actor)) -> dict:
    items = db.scalars(select(RoutingWorkflow).order_by(RoutingWorkflow.id.desc())).all()
    return success_response({
        "items": [serialize(item) for item in items],
        "page": 1, "page_size": len(items), "total": len(items),
    }).model_dump()


@router.get("/workflows/{workflow_id}")
def workflow_detail(
    workflow_id: int, db: Session = Depends(get_db), _user: User = Depends(actor),
) -> dict:
    return success_response(serialize(get_workflow(db, workflow_id))).model_dump()


@router.post("/workflows/{workflow_id}/simulate")
def simulate_workflow(
    workflow_id: int, payload: SimulationPayload,
    db: Session = Depends(get_db), _user: User = Depends(actor),
) -> dict:
    item = get_workflow(db, workflow_id)
    definition = Definition.model_validate(item.definition)
    models = validate_bindings(db, definition, payload.bindings, item.model_type)
    if any(value < 0 for value in payload.latencies.values()):
        raise HTTPException(422, "延迟毫秒数不能为负数。")
    return success_response(simulate(
        definition, models, bindings=payload.bindings, latencies=payload.latencies,
        round_robin_index=payload.round_robin_index,
        region=payload.region, stream=payload.stream, seed=payload.seed,
    )).model_dump()
