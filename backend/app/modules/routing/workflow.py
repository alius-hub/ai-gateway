from __future__ import annotations

import random
import re
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ProviderModel

ModelType = Literal["llm", "embedding", "rerank", "asr", "tts", "ocr"]
OUTPUTS = {
    "start": {"next"}, "condition": {"true", "false"},
    "select": {"unavailable"}, "weighted": {"unavailable"}, "reject": set(),
    "single": {"unavailable"}, "round_robin": {"unavailable"},
    "least_latency": {"unavailable"},
}
SLOT_TYPES = {"single", "round_robin", "least_latency"}


class Node(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=64)
    type: Literal["start", "condition", "select", "weighted", "reject", "single", "round_robin", "least_latency"]
    config: dict[str, Any] = Field(default_factory=dict)
    x: int = Field(default=40, ge=0, le=4000)
    y: int = Field(default=40, ge=0, le=4000)


class Edge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    target: str
    label: str


class Definition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nodes: list[Node] = Field(min_length=2, max_length=50)
    edges: list[Edge] = Field(min_length=1, max_length=100)


class SimulationOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    region: str = Field(default="", max_length=64)
    stream: bool = False
    seed: int = 0
    round_robin_index: int = Field(default=0, ge=0)
    latencies: dict[int, int] = Field(default_factory=dict)


class SimulationPayload(SimulationOptions):
    bindings: dict[str, list[int]] = Field(default_factory=dict)


def invalid(reason: str) -> None:
    raise HTTPException(422, reason)


def validate_definition(db: Session, definition: Definition, model_type: str | None = None) -> dict[int, ProviderModel]:
    nodes = {node.id: node for node in definition.nodes}
    if len(nodes) != len(definition.nodes) or any(
        not re.fullmatch(r"[A-Za-z0-9_-]+", node.id) for node in definition.nodes
    ):
        invalid("节点 ID 必须唯一，且只能包含字母、数字、下划线和连字符。")
    starts = [node.id for node in definition.nodes if node.type == "start"]
    if len(starts) != 1 or not any(node.type in {"select", "weighted", *SLOT_TYPES} for node in definition.nodes):
        invalid("流程必须有且仅有一个开始节点，并包含至少一个模型选择节点。")
    links: dict[str, dict[str, str]] = {key: {} for key in nodes}
    for edge in definition.edges:
        if edge.source not in nodes or edge.target not in nodes:
            invalid("连线指向不存在的节点。")
        if edge.label not in OUTPUTS[nodes[edge.source].type]:
            invalid(f"节点 {edge.source} 不支持出口 {edge.label}。")
        if edge.label in links[edge.source]:
            invalid(f"节点 {edge.source} 的 {edge.label} 出口只能连接一次。")
        links[edge.source][edge.label] = edge.target
    ids: set[int] = set()
    slots: set[str] = set()
    for node in definition.nodes:
        config = node.config
        expected = {
            "start": set(), "condition": {"field", "value"},
            "select": {"model_id"}, "weighted": {"candidates"}, "reject": set(),
            "single": {"slot"}, "round_robin": {"slot"}, "least_latency": {"slot"},
        }[node.type]
        if set(config) != expected:
            invalid(f"节点 {node.id} 的配置字段应为 {', '.join(sorted(expected)) or '空'}。")
        if node.type == "condition":
            if config["field"] not in ("region", "stream") or (
                not isinstance(config["value"], str) if config["field"] == "region"
                else not isinstance(config["value"], bool)
            ):
                invalid(f"节点 {node.id} 的条件只支持地域字符串或流式布尔值。")
        if node.type == "select":
            if type(config["model_id"]) is not int or config["model_id"] <= 0:
                invalid(f"节点 {node.id} 的模型 ID 无效。")
            ids.add(config["model_id"])
        if node.type in SLOT_TYPES:
            slot = config["slot"]
            if not isinstance(slot, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", slot) or slot in slots:
                invalid(f"节点 {node.id} 的槽位名称无效或重复。")
            slots.add(slot)
        if node.type == "weighted":
            candidates = config["candidates"]
            if not isinstance(candidates, list) or not 1 <= len(candidates) <= 30:
                invalid(f"节点 {node.id} 的加权候选模型数量无效。")
            seen: set[int] = set()
            for candidate in candidates:
                if not isinstance(candidate, dict) or set(candidate) != {"model_id", "weight"}:
                    invalid(f"节点 {node.id} 的加权配置无效。")
                model_id, weight = candidate["model_id"], candidate["weight"]
                if type(model_id) is not int or model_id <= 0 or type(weight) is not int or not 1 <= weight <= 10000 or model_id in seen:
                    invalid(f"节点 {node.id} 存在重复模型或无效权重。")
                seen.add(model_id)
                ids.add(model_id)
        if node.type in ("start", "condition") and set(links[node.id]) != OUTPUTS[node.type]:
            invalid(f"节点 {node.id} 的所有出口必须连接。")
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(key: str) -> None:
        if key in visiting:
            invalid("路由流程不能包含循环。")
        if key in visited:
            return
        visiting.add(key)
        for target in links[key].values():
            visit(target)
        visiting.remove(key)
        visited.add(key)

    visit(starts[0])
    if len(visited) != len(nodes):
        invalid("所有节点都必须从开始节点可达。")
    models = {model.id: model for model in db.scalars(
        select(ProviderModel).where(ProviderModel.id.in_(ids))
    ).all()}
    if (len(models) != len(ids) or len({model.model_type for model in models.values()}) > 1
            or (model_type and any(model.model_type != model_type for model in models.values()))):
        invalid("旧流程引用的接入模型不存在或与聚合模型类型不一致。")
    return models


def validate_bindings(db: Session, definition: Definition, bindings: dict[str, list[int]],
                      model_type: str | None = None) -> dict[int, ProviderModel]:
    models = validate_definition(db, definition, model_type)
    slots = {node.config["slot"]: node for node in definition.nodes if node.type in SLOT_TYPES}
    if set(bindings) != set(slots):
        invalid("请为流程的每个终点槽位绑定模型，且不要传入多余槽位。")
    ids: set[int] = set()
    for slot, node in slots.items():
        candidates = bindings[slot]
        minimum = 1 if node.type == "single" else 2
        if (not isinstance(candidates, list) or not minimum <= len(candidates) <= 30
                or any(type(value) is not int or value <= 0 for value in candidates)
                or len(set(candidates)) != len(candidates)):
            invalid(f"槽位 {slot} 需要 {minimum} 至 30 个不重复的接入模型。")
        if node.type == "single" and len(candidates) != 1:
            invalid(f"槽位 {slot} 只能绑定一个接入模型。")
        ids.update(candidates)
    bound = {model.id: model for model in db.scalars(
        select(ProviderModel).where(ProviderModel.id.in_(ids))
    ).all()}
    if len(bound) != len(ids):
        invalid("槽位绑定了不存在的接入模型。")
    models.update(bound)
    if model_type and any(model.model_type != model_type for model in models.values()):
        invalid("槽位中的模型类型必须与聚合模型一致。")
    if not model_type and len({model.model_type for model in models.values()}) > 1:
        invalid("一次模拟中绑定的接入模型必须属于同一种类型。")
    return models


def simulate(definition: Definition, models: dict[int, ProviderModel], *,
             bindings: dict[str, list[int]] | None = None,
             latencies: dict[int, int] | None = None, round_robin_index: int = 0,
             region: str = "", stream: bool = False, seed: int = 0) -> dict:
    bindings = bindings or {}
    latencies = latencies or {}
    nodes = {node.id: node for node in definition.nodes}
    links = {(edge.source, edge.label): edge.target for edge in definition.edges}
    current = next(node.id for node in definition.nodes if node.type == "start")
    trace: list[dict] = []
    rng = random.Random(seed)
    while True:
        node = nodes[current]
        config = node.config
        output = ""
        selected: int | None = None
        if node.type == "start":
            output = "next"
        elif node.type == "condition":
            actual = region if config["field"] == "region" else stream
            output = "true" if actual == config["value"] else "false"
        elif node.type == "select":
            model_id = config["model_id"]
            selected = model_id if models[model_id].status == 1 else None
            output = "selected" if selected else "unavailable"
        elif node.type == "weighted":
            available = [candidate for candidate in config["candidates"]
                         if models[candidate["model_id"]].status == 1]
            if available:
                selected = rng.choices(
                    [candidate["model_id"] for candidate in available],
                    weights=[candidate["weight"] for candidate in available], k=1,
                )[0]
            output = "selected" if selected else "unavailable"
        elif node.type in SLOT_TYPES:
            available = [model_id for model_id in bindings[config["slot"]]
                         if models[model_id].status == 1]
            if node.type == "single" and available:
                selected = available[0]
            elif node.type == "round_robin" and available:
                selected = available[round_robin_index % len(available)]
            elif node.type == "least_latency":
                measured = [model_id for model_id in available if model_id in latencies]
                if measured:
                    selected = min(measured, key=lambda model_id: (latencies[model_id], model_id))
            output = "selected" if selected else "unavailable"
        else:
            output = "rejected"
        trace.append({"node_id": current, "type": node.type, "outcome": output})
        if selected:
            return {"selected_model_id": selected, "trace": trace}
        following = links.get((current, output))
        if following is None:
            return {"selected_model_id": None, "trace": trace}
        current = following
