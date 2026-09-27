from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ProviderModel

BUILTIN_STRATEGIES = (
    {"code": "single", "name": "单模型", "description": "固定使用一个接入模型。", "min_models": 1},
    {"code": "round_robin", "name": "轮询分流", "description": "按候选顺序依次选择可用模型。", "min_models": 2},
    {"code": "least_latency", "name": "最低延迟", "description": "从有延迟指标的可用模型中选择最低延迟者。", "min_models": 2},
)
STRATEGIES = {strategy["code"]: strategy for strategy in BUILTIN_STRATEGIES}


def validate_candidates(db: Session, strategy: str, ids: list[int], model_type: str) -> dict[int, ProviderModel]:
    if strategy not in STRATEGIES:
        raise HTTPException(422, "请选择内置路由策略。")
    minimum = STRATEGIES[strategy]["min_models"]
    if not minimum <= len(ids) <= (1 if strategy == "single" else 30):
        raise HTTPException(422, f"该策略需要 {'恰好一个' if strategy == 'single' else '2 至 30 个'}接入模型。")
    if any(type(value) is not int or value <= 0 for value in ids) or len(set(ids)) != len(ids):
        raise HTTPException(422, "候选模型 ID 必须是互不重复的正整数。")
    models = {model.id: model for model in db.scalars(
        select(ProviderModel).where(ProviderModel.id.in_(ids))
    ).all()}
    if len(models) != len(ids) or any(model.model_type != model_type for model in models.values()):
        raise HTTPException(422, "候选接入模型不存在或与聚合模型类型不一致。")
    return models


def choose_model(strategy: str, ids: list[int], models: dict[int, ProviderModel], *,
                 round_robin_index: int = 0, latencies: dict[int, int] | None = None,
                 fallback_model_id: int | None = None) -> dict:
    if strategy not in STRATEGIES:
        raise HTTPException(422, "聚合模型尚未使用内置路由策略。")
    available = [model_id for model_id in ids if models[model_id].status == 1]
    selected: int | None = None
    if strategy == "single" and available:
        selected = available[0]
    elif strategy == "round_robin" and available:
        selected = available[round_robin_index % len(available)]
    elif strategy == "least_latency":
        measured = [model_id for model_id in available if model_id in (latencies or {})]
        if measured:
            selected = min(measured, key=lambda model_id: ((latencies or {})[model_id], model_id))
    trace = [{"strategy": strategy, "outcome": "selected" if selected else "unavailable"}]
    if selected is None and fallback_model_id is not None:
        fallback = models[fallback_model_id]
        if fallback.status == 1:
            selected = fallback_model_id
        trace.append({"strategy": "fallback", "outcome": "selected" if selected else "unavailable"})
    return {"selected_model_id": selected, "trace": trace}
