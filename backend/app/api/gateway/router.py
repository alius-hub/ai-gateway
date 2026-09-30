from __future__ import annotations

# ruff: noqa: B008
import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from itertools import count
from time import perf_counter
from typing import Any
from uuid import uuid4

import httpx
from anyio import CancelScope, to_thread
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.exc import TimeoutError as PoolTimeout
from sqlalchemy.orm import Session

from app.db.models import (
    AggregatedModel,
    ApiKey,
    Organization,
    Project,
    ProjectMember,
    Provider,
    ProviderModel,
    ProviderProtocol,
    ProviderSecret,
    RequestLog,
    UsageRecord,
    User,
)
from app.db.session import get_db
from app.modules.gateway.adapters import normalize, prepare, reasoning_count, usage_counts
from app.modules.gateway.budgets import baselines as budget_baselines
from app.modules.gateway.budgets import increment
from app.modules.gateway.limits import Limiter, cooldown_key, limiter, unavailable
from app.modules.gateway.pricing import cents as price_cents
from app.modules.gateway.pricing import priced
from app.modules.gateway.runtime import upstream_client
from app.modules.gateway.streaming import StreamUsage, events, translate
from app.modules.model.playground import read_key
from app.modules.routing.strategies import choose_model

gateway_router = APIRouter(tags=["Gateway API"])
rounds = count()
logger = logging.getLogger(__name__)


class ChatBody(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str = Field(min_length=1)
    messages: list[dict[str, Any]] = Field(min_length=1)
    max_tokens: int = Field(default=1024, ge=1, le=32768)
    stream: bool = False


class EmbeddingBody(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str = Field(min_length=1)
    input: str | list[str]


class RerankBody(BaseModel):
    model: str = Field(min_length=1)
    query: str = Field(min_length=1)
    documents: list[str] = Field(min_length=1, max_length=100)
    top_n: int | None = Field(default=None, ge=1)


class OcrBody(BaseModel):
    model: str = Field(min_length=1)
    image_url: str = Field(min_length=1)


class ImageBody(BaseModel):
    model: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    size: str = "1024x1024"
    n: int = Field(default=1, ge=1, le=10)


MODEL_TYPES = {
    "chat": ("llm", "vlm"), "embedding": ("embedding",),
    "rerank": ("rerank",), "ocr": ("ocr",), "image": ("text_to_image",),
}


def error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, "type": "gateway_error"}},
                        status_code=status)


def authenticate_raw(request: Request, db: Session) -> ApiKey:
    auth = request.headers.get("authorization")
    raw = (
        auth[7:] if auth and auth.lower().startswith("bearer ")
        else request.headers.get("x-api-key")
    )
    if not raw or len(raw) > 256:
        raise HTTPException(401, "invalid_api_key")
    key = db.scalar(select(ApiKey).where(
        ApiKey.key_hash == hashlib.sha256(raw.encode()).hexdigest(),
        ApiKey.deleted_at.is_(None),
    ))
    if key is None or key.status != 1:
        raise HTTPException(401, "invalid_api_key")
    expiry = key.expires_at
    if expiry and (
        expiry.replace(tzinfo=UTC) if expiry.tzinfo is None else expiry
    ) <= datetime.now(UTC):
        raise HTTPException(401, "api_key_expired")
    if key.scope_type == "user":
        owner = db.get(User, key.user_id)
        if owner is None or owner.status != 1 or owner.deleted_at is not None:
            raise HTTPException(403, "key_owner_disabled")
    elif key.scope_type == "project":
        project = db.get(Project, key.project_id)
        if project is None or project.status != 1 or project.deleted_at is not None:
            raise HTTPException(403, "project_forbidden")
        if project.organization_id != key.organization_id:
            raise HTTPException(403, "project_forbidden")
        if key.user_id is not None:
            owner = db.get(User, key.user_id)
            member = db.scalar(select(ProjectMember.id).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == key.user_id, ProjectMember.status == 1,
            ))
            if (owner is None or owner.status != 1 or owner.deleted_at is not None
                    or member is None):
                raise HTTPException(403, "key_owner_disabled")
    else:
        raise HTTPException(401, "invalid_api_key")
    if key.organization_id is not None:
        org = db.get(Organization, key.organization_id)
        if org is None or org.status != 1 or org.deleted_at is not None:
            raise HTTPException(403, "organization_forbidden")
    return key


def database_phase(db: Session, operation, *args):
    """Detach snapshots and release the connection before returning to async code."""
    try:
        return operation(*args)
    except PoolTimeout as exc:
        raise HTTPException(503, "database_capacity_exceeded") from exc
    finally:
        db.expunge_all()
        db.close()


def authenticate(request: Request, db: Session = Depends(get_db)) -> ApiKey:
    return database_phase(db, authenticate_raw, request, db)


def authorized_models(db: Session, key: ApiKey, model_name: str,
                      model_types: tuple[str, ...], *, round_index: int | None = None,
                      excluded_ids: set[int] | None = None,
                      ) -> tuple[ProviderModel, AggregatedModel | None]:
    grants = key.allowed_models if isinstance(key.allowed_models, dict) else {}
    aggregate_ids = grants.get("aggregate_ids", [])
    access_ids = grants.get("access_ids", [])
    aggregate = db.scalar(select(AggregatedModel).where(
        AggregatedModel.public_model_name == model_name,
        AggregatedModel.id.in_(aggregate_ids),
        AggregatedModel.status == 1,
        AggregatedModel.model_type.in_(model_types),
    )) if aggregate_ids else None
    direct = db.scalar(select(ProviderModel).where(
        ProviderModel.access_model_code == model_name,
        ProviderModel.id.in_(access_ids),
        ProviderModel.status == 1,
        ProviderModel.model_type.in_(model_types),
    )) if access_ids else None
    if aggregate and direct:
        raise HTTPException(409, "ambiguous_model_name")
    if direct:
        return direct, None
    if aggregate:
        ids = aggregate.routing_model_ids or []
        candidate_ids = list(dict.fromkeys(ids + (
            [aggregate.fallback_model_id] if aggregate.fallback_model_id else [])))
        candidates = {item.id: item for item in db.scalars(
            select(ProviderModel).where(ProviderModel.id.in_(candidate_ids))
        )}
        if len(candidates) != len(candidate_ids) or any(
            item.model_type != aggregate.model_type for item in candidates.values()
        ):
            raise HTTPException(503, "model_unavailable")
        selection = choose_model(
            aggregate.default_routing_strategy, ids, candidates,
            round_robin_index=next(rounds) if round_index is None else round_index,
            latencies={model_id: index for index, model_id in enumerate(ids)},
            fallback_model_id=aggregate.fallback_model_id, excluded_ids=excluded_ids,
        )
        selected = candidates.get(selection["selected_model_id"])
        if selected:
            return selected, aggregate
        raise HTTPException(503, "model_unavailable")
    raise HTTPException(403, "model_not_allowed")


def retry_candidates(db: Session, aggregate: AggregatedModel | None,
                     initial: ProviderModel, round_index: int) -> list[ProviderModel]:
    if aggregate is None or not aggregate.retry_on_failure \
            or aggregate.default_routing_strategy not in ("round_robin", "least_latency"):
        return [initial]
    ids = aggregate.routing_model_ids or []
    candidate_ids = list(dict.fromkeys(ids + (
        [aggregate.fallback_model_id] if aggregate.fallback_model_id else [])))
    models = {item.id: item for item in db.scalars(
        select(ProviderModel).where(ProviderModel.id.in_(candidate_ids))
    )}
    ordered = [initial]
    excluded = {initial.id}
    while len(excluded) < len(models):
        selected = choose_model(
            aggregate.default_routing_strategy, ids, models, round_robin_index=round_index,
            latencies={model_id: index for index, model_id in enumerate(ids)},
            fallback_model_id=aggregate.fallback_model_id, excluded_ids=excluded,
        )["selected_model_id"]
        if selected is None:
            break
        ordered.append(models[selected])
        excluded.add(selected)
    return ordered


COOLDOWN_SECONDS = 300


async def cooling_models(service: Limiter, candidates: list[ProviderModel]) -> set[int]:
    if not candidates:
        return set()
    states = await service.client.mget([cooldown_key(item.id) for item in candidates])
    return {item.id for item, state in zip(candidates, states, strict=True) if state is not None}


async def cool_failed_model(service: Limiter, aggregate: AggregatedModel | None,
                            model: ProviderModel) -> None:
    if aggregate is not None and aggregate.retry_on_failure:
        try:
            await service.client.set(cooldown_key(model.id), "1", ex=COOLDOWN_SECONDS)
        except RedisError:
            logger.exception("Unable to mark model %s unavailable for retry", model.id)


def price_signature(model: ProviderModel) -> tuple:
    return (
        model.currency, model.input_price, model.output_price, model.price_unit_k,
        model.tiered_pricing, json.dumps(model.input_price_tiers, sort_keys=True),
        json.dumps(model.output_price_tiers, sort_keys=True),
    )


def connection(db: Session, model: ProviderModel) -> tuple[str, str, str | None, float]:
    provider = db.get(Provider, model.provider_id)
    protocol = db.get(ProviderProtocol, model.protocol_id) if model.protocol_id else None
    secret = db.get(ProviderSecret, model.secret_id) if model.secret_id else None
    if provider is None or provider.status != 1 or protocol is None or protocol.status != 1 \
            or protocol.provider_id != model.provider_id \
            or model.secret_id and (
                secret is None or secret.status != 1 or secret.provider_id != model.provider_id
            ):
        raise HTTPException(503, "model_unavailable")
    return (
        protocol.protocol_type, model.base_url or protocol.base_url or provider.base_url,
        read_key(secret), (model.timeout_ms or 60000) / 1000,
    )


def fingerprint(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def token_estimate(body: dict, kind: str) -> int:
    if kind == "chat":
        raw = json.dumps(body["messages"], ensure_ascii=False)
        return (len(raw.encode()) + 3) // 4 + body["max_tokens"]
    raw = json.dumps({field: value for field, value in body.items() if field != "model"},
                     ensure_ascii=False)
    return (len(raw.encode()) + 3) // 4 + (body.get("n", 0) or 0) + 1


def charge(model: ProviderModel, input_tokens: int | None, output_tokens: int | None,
           reservation_cents: int) -> int:
    if not priced(model):
        return 0
    if input_tokens is None or output_tokens is None:
        return reservation_cents
    return price_cents(model, input_tokens, output_tokens)


def has_output_fragment(protocol: str, event: str, data: str, fragment: bytes | None) -> bool:
    if not fragment or data == "[DONE]":
        return False
    if protocol not in ("openai", "openai_compatible"):
        return event == "content_block_delta" if protocol in ("claude", "anthropic") else True
    payload = json.loads(data)
    return any(
        isinstance(choice.get("delta"), dict) and any(
            choice["delta"].get(field) for field in ("content", "reasoning_content")
        )
        for choice in payload.get("choices", []) if isinstance(choice, dict)
    )


def record_sync(db: Session, request: Request, key: ApiKey, model: ProviderModel,
           aggregate: AggregatedModel | None, status: int, latency: int, tokens: int,
           input_tokens: int | None, output_tokens: int | None, error_code: str | None,
           charged_cents: int = 0, reasoning_tokens: int | None = None,
           ttft_ms: int | None = None, tpot_ms: float | None = None,
           attempt_failure: bool = False, provider_status: str | None = None) -> None:
    recorded_at = datetime.now(UTC)
    request_id = request.scope.setdefault(
        "gateway_request_id",
        request.scope["call_archive"].request_id
        if "call_archive" in request.scope else f"req_{uuid4().hex}",
    )
    raw_key = request.headers.get("authorization", "").partition(" ")[2].strip()
    masked_key = f"{raw_key[:8]}****{raw_key[-4:]}" if len(raw_key) > 12 else None
    log = RequestLog(
        created_at=recorded_at.replace(tzinfo=None),
        api_key_masked=masked_key,
        request_id=f"req_{uuid4().hex}" if attempt_failure else request_id,
        organization_id=key.organization_id,
        project_id=key.project_id, api_key_id=key.id,
        aggregate_model_id=aggregate.id if aggregate else None,
        provider_id=model.provider_id, provider_model_id=model.id,
        public_model_name=aggregate.public_model_name if aggregate else model.access_model_code,
        model_type=model.model_type, endpoint=request.url.path, requester_ip=(
            request.client.host if request.client else "unknown"),
        http_status=status, latency_ms=latency, error_code=error_code,
        ttft_ms=ttft_ms, tpot_ms=tpot_ms, provider_status=provider_status,
        error_message=f"Attempt for {request_id}" if attempt_failure else None,
    )
    db.add(log)
    db.flush()
    if tokens:
        db.add(UsageRecord(
            created_at=recorded_at.replace(tzinfo=None),
            request_log_id=log.id, organization_id=key.organization_id,
            project_id=key.project_id, api_key_id=key.id,
            aggregate_model_id=aggregate.id if aggregate else None,
            provider_id=model.provider_id, provider_model_id=model.id,
            model_type=model.model_type, input_tokens=input_tokens,
            output_tokens=output_tokens, total_tokens=tokens,
            reasoning_tokens=reasoning_tokens,
            non_reasoning_tokens=(
                output_tokens - reasoning_tokens
                if output_tokens is not None and reasoning_tokens is not None
                and reasoning_tokens <= output_tokens else None
            ),
            estimated_cost=Decimal(charged_cents) / 100 if priced(model) else None,
            currency=model.currency,
        ))
    if tokens and priced(model):
        increment(db, key, charged_cents, recorded_at)
    db.commit()
    if not attempt_failure:
        request.scope["db_recorded"] = True


async def record(db: Session, *args, **kwargs) -> None:
    def write():
        return database_phase(db, lambda: record_sync(db, *args, **kwargs))
    await to_thread.run_sync(write)


@gateway_router.get("/models")
def list_models(db: Session = Depends(get_db), key: ApiKey = Depends(authenticate)) -> dict:
    grants = key.allowed_models if isinstance(key.allowed_models, dict) else {}
    models = []
    for item in db.scalars(select(AggregatedModel).where(
        AggregatedModel.id.in_(grants.get("aggregate_ids", [])), AggregatedModel.status == 1,
    )):
        models.append({"id": item.public_model_name, "object": "model",
                       "owned_by": "ai-gateway", "model_type": item.model_type})
    for item in db.scalars(select(ProviderModel).where(
        ProviderModel.id.in_(grants.get("access_ids", [])), ProviderModel.status == 1,
    )):
        models.append({"id": item.access_model_code, "object": "model",
                       "owned_by": "ai-gateway", "model_type": item.model_type})
    db.expunge_all()
    db.close()
    return {"data": models}


@gateway_router.get("/queue/{ticket}")
async def queue_position(ticket: str, key: ApiKey = Depends(authenticate)) -> dict:
    if len(ticket) != 32 or any(ch not in "0123456789abcdef" for ch in ticket):
        raise HTTPException(404, "queue_ticket_not_found")
    service = limiter()
    try:
        position = await service.position(key, ticket)
    except RedisError as exc:
        unavailable(exc)
    finally:
        await service.close()
    if not position:
        raise HTTPException(404, "queue_ticket_not_found")
    return {"ticket": ticket, "position": position, "status": "waiting"}


async def stream_response(
    request: Request, db: Session, key: ApiKey, model: ProviderModel,
    aggregate: AggregatedModel | None, service: Limiter, reservation,
    protocol: str, url: str, headers: dict, upstream_body: dict, timeout: float,
    public_name: str,
    alternatives: list[tuple[ProviderModel, str, str, dict, dict, float]] | None = None,
) -> Response:
    await to_thread.run_sync(database_phase, db, lambda: None)
    started = perf_counter()
    attempts = [(model, protocol, url, headers, upstream_body, timeout), *(alternatives or [])]
    archive = request.scope.get("call_archive")
    for index, attempt in enumerate(attempts):
        model, protocol, url, headers, upstream_body, timeout = attempt
        try:
            client = await upstream_client(request, service, model)
        except asyncio.CancelledError:
            with CancelScope(shield=True):
                await service.settle(reservation, 0, 0)
            raise
        try:
            upstream_request = client.build_request(
                "POST", url, headers=headers, json=upstream_body, timeout=timeout,
            )
            if archive:
                archive.upstream(upstream_request)
            upstream = await client.send(upstream_request, stream=True)
            if archive:
                archive.upstream_response(upstream)
        except (httpx.RequestError, httpx.TimeoutException) as exc:
            await client.aclose()
            status = 504 if isinstance(exc, httpx.TimeoutException) else 502
            code = "provider_timeout" if status == 504 else "provider_error"
            await cool_failed_model(service, aggregate, model)
            if index + 1 < len(attempts):
                await record(db, request, key, model, aggregate, status,
                       round((perf_counter() - started) * 1000), 0, None, None, code,
                       attempt_failure=True)
                continue
            await service.settle(reservation, 0, 0)
            await record(db, request, key, model, aggregate, status,
                   round((perf_counter() - started) * 1000), 0, None, None, code)
            return error(status, code, code)
        except asyncio.CancelledError:
            with CancelScope(shield=True):
                await client.aclose()
                await service.settle(reservation, reservation.tokens, reservation.cents)
                await record(db, request, key, model, aggregate, 499,
                       round((perf_counter() - started) * 1000), reservation.tokens,
                       None, None, "client_disconnected", reservation.cents)
            raise
        if upstream.status_code >= 400 or upstream.is_redirect:
            upstream_status = str(upstream.status_code)
            await upstream.aclose()
            await client.aclose()
            await cool_failed_model(service, aggregate, model)
            if index + 1 < len(attempts):
                await record(db, request, key, model, aggregate, 502,
                       round((perf_counter() - started) * 1000), 0, None, None,
                       "provider_error", attempt_failure=True, provider_status=upstream_status)
                continue
            await service.settle(reservation, 0, 0)
            await record(db, request, key, model, aggregate, 502,
                   round((perf_counter() - started) * 1000), 0, None, None, "provider_error",
                   provider_status=upstream_status)
            return error(502, "provider_error", "provider_error")
        break
    if "text/event-stream" not in upstream.headers.get("content-type", "").lower():
        await upstream.aclose()
        await client.aclose()
        await cool_failed_model(service, aggregate, model)
        await service.settle(reservation, reservation.tokens, reservation.cents)
        await record(db, request, key, model, aggregate, 502,
               round((perf_counter() - started) * 1000), reservation.tokens,
               None, None, "invalid_provider_stream", reservation.cents)
        return error(502, "invalid_provider_stream", "invalid_provider_stream")

    async def chunks():
        client.owner = asyncio.current_task()
        usage = StreamUsage()
        status, code = 200, None
        first_output: float | None = None
        try:
            async for event, data in events(
                upstream, archive=lambda data: archive.write("upstream_response.bin", data)
                if archive else None,
            ):
                fragment = translate(protocol, event, data, public_name, usage)
                if fragment:
                    if first_output is None and has_output_fragment(
                        protocol, event, data, fragment,
                    ):
                        first_output = perf_counter()
                    yield fragment
            if not usage.completed:
                status, code = 502, "provider_stream_interrupted"
                yield b'event: gateway_error\ndata: {"code":"provider_stream_interrupted"}\n\n'
        except (httpx.RequestError, httpx.TimeoutException, ValueError,
                TypeError, KeyError, IndexError, AttributeError):
            status, code = 502, "provider_stream_interrupted"
            yield b'event: gateway_error\ndata: {"code":"provider_stream_interrupted"}\n\n'
        except (asyncio.CancelledError, GeneratorExit):
            status, code = 499, "client_disconnected"
            raise
        finally:
            with CancelScope(shield=True):
                finished = perf_counter()
                await upstream.aclose()
                await client.aclose()
                try:
                    if code == "provider_stream_interrupted":
                        await cool_failed_model(service, aggregate, model)
                    actual = (
                        usage.total if usage.completed and usage.total is not None
                        else reservation.tokens
                    )
                    billed = charge(model, usage.input_tokens if usage.completed else None,
                                    usage.output_tokens if usage.completed else None,
                                    reservation.cents)
                    await service.settle(reservation, actual, billed)
                    await record(db, request, key, model, aggregate, status,
                           round((finished - started) * 1000), actual,
                           usage.input_tokens if usage.completed else None,
                           usage.output_tokens if usage.completed else None, code, billed,
                           reasoning_tokens=usage.reasoning_tokens if usage.completed else None,
                           ttft_ms=round((first_output - started) * 1000)
                           if first_output is not None else None,
                           tpot_ms=round((finished - first_output) * 1000 /
                                         (usage.output_tokens - 1), 3)
                           if first_output is not None and usage.completed
                           and usage.output_tokens is not None and usage.output_tokens > 1
                           else None)
                finally:
                    await service.close()
        if status == 200 and usage.completed:
            yield b"data: [DONE]\n\n"

    return StreamingResponse(
        chunks(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )



def prepare_admission(db: Session, key: ApiKey, body: dict, kind: str, round_index: int):
    base_model, aggregate = authorized_models(
        db, key, body["model"], MODEL_TYPES[kind], round_index=round_index,
    )
    pool = retry_candidates(db, aggregate, base_model, round_index)
    project = db.get(Project, key.project_id) if key.project_id else None
    budgeted = key.amount_budget is not None or (
        project is not None and project.amount_budget is not None
    )
    if budgeted and any(not priced(candidate) for candidate in pool):
        raise HTTPException(503, "model_price_missing")
    cost = token_estimate(body, kind)
    output_estimate = body["max_tokens"] if kind == "chat" else 0
    estimated_cents = max(
        (price_cents(candidate, cost - output_estimate, output_estimate)
         if priced(candidate) else 0 for candidate in pool), default=0,
    )
    key_spent, project_spent = budget_baselines(db, key, project)
    options = {"cents": estimated_cents, "project_id": key.project_id,
               "project_limit": int(project.amount_budget * 100)
               if project is not None and project.amount_budget is not None else 0,
               "money_baseline": key_spent, "project_baseline": project_spent}
    return (base_model, aggregate, pool, options, base_model.id,
            {candidate.id: price_signature(candidate) for candidate in pool})


def prepare_attempts(db: Session, request: Request, body: dict, kind: str,
                     round_index: int, base_model_id: int, price_snapshot: dict,
                     excluded: set[int]):
    key = authenticate_raw(request, db)
    base_model, aggregate = authorized_models(
        db, key, body["model"], MODEL_TYPES[kind], round_index=round_index,
    )
    pool = retry_candidates(db, aggregate, base_model, round_index)
    if base_model.id != base_model_id or {
        candidate.id: price_signature(candidate) for candidate in pool
    } != price_snapshot:
        raise HTTPException(409, "model_price_changed")
    if excluded:
        model, aggregate = authorized_models(
            db, key, body["model"], MODEL_TYPES[kind],
            round_index=round_index, excluded_ids=excluded,
        )
    else:
        model = base_model
    candidates = [item for item in retry_candidates(db, aggregate, model, round_index)
                  if item.id not in excluded]
    attempts = []
    for candidate in candidates:
        try:
            protocol, base, secret, timeout = connection(db, candidate)
            url, headers, upstream_body = prepare(
                protocol, base, candidate.provider_model_name, secret, body, kind,
            )
            if kind == "chat" and body["stream"] and protocol in ("openai", "openai_compatible"):
                upstream_body["stream_options"] = {"include_usage": True}
            attempts.append((candidate, protocol, url, headers, upstream_body, timeout))
        except HTTPException as exc:
            if len(candidates) == 1 or exc.status_code != 503:
                raise
    if not attempts:
        raise HTTPException(503, "model_unavailable")
    return key, aggregate, attempts


async def forward(request: Request, body: dict, kind: str, db: Session, key: ApiKey,
                  ticket: str | None) -> Response:
    round_index = next(rounds)
    try:
        (base_model, aggregate, pool, money_options, base_model_id,
         price_snapshot) = await to_thread.run_sync(
            database_phase, db, prepare_admission, db, key, body, kind, round_index,
        )
    except HTTPException as exc:
        return error(exc.status_code, str(exc.detail), str(exc.detail))
    cost = token_estimate(body, kind)
    digest = fingerprint(body)
    service: Limiter = limiter()
    reservation = None
    deferred_close = False
    sent_upstream = False
    try:
        if key.wait_mode == "queue":
            state, rank, token, reservation = await service.admit(
                key, cost, digest, ticket, **money_options)
        else:
            if ticket:
                return error(400, "invalid_ticket", "This key does not support queue tickets.")
            state, rank, token, reservation = await service.wait(
                key, cost, digest, **money_options)
        if state == "queued":
            return JSONResponse(
                {"ticket": token, "position": rank, "status": "waiting",
                 "poll_url": f"/v1/queue/{token}", "retry_after_ms": 1000},
                status_code=202, headers={"Retry-After": "1"},
            )
        if state != "admitted":
            code = {"quota": "quota_exceeded", "amount_quota": "amount_quota_exceeded",
                    "project_budget": "project_budget_exceeded", "too_large": "tpm_exceeded",
                    "invalid_ticket": "invalid_ticket"}.get(state, "rate_limit_exceeded")
            return error(400 if state == "invalid_ticket" else 429, code, code)
        assert reservation is not None
        try:
            excluded = (await cooling_models(service, pool)
                        if aggregate is not None and aggregate.retry_on_failure else set())
            key, aggregate, attempts = await to_thread.run_sync(
                database_phase, db, prepare_attempts, db, request, body, kind,
                round_index, base_model_id, price_snapshot, excluded,
            )
        except Exception:
            await service.settle(reservation, 0, 0)
            raise
        if kind == "chat" and body["stream"]:
            response = await stream_response(
                request, db, key, attempts[0][0], aggregate, service, reservation,
                *attempts[0][1:], body["model"], alternatives=attempts[1:],
            )
            deferred_close = isinstance(response, StreamingResponse)
            return response
        started = perf_counter()
        for index, attempt in enumerate(attempts):
            attempt_started = perf_counter()
            model, protocol, url, headers, upstream_body, timeout = attempt
            status, payload, code, estimated, received_success = 502, None, None, False, False
            provider_status = None
            try:
                async with await upstream_client(request, service, model) as client:
                    upstream_request = client.build_request(
                        "POST", url, headers=headers, json=upstream_body, timeout=timeout,
                    )
                    archive = request.scope.get("call_archive")
                    if archive:
                        archive.upstream(upstream_request)
                    sent_upstream = True
                    response = await client.send(upstream_request)
                    if archive:
                        archive.upstream_response(response)
                        archive.write("upstream_response.bin", response.content)
                if response.status_code >= 400 or response.is_redirect:
                    code = "provider_error"
                    provider_status = str(response.status_code)
                else:
                    received_success = True
                    raw_payload = response.json()
                    if not isinstance(raw_payload, dict):
                        raise ValueError("invalid provider response")
                    payload = normalize(raw_payload, protocol, kind, body["model"])
                    counts = usage_counts(raw_payload, protocol)
                    if counts is None and kind in ("chat", "embedding"):
                        code = "invalid_provider_usage"
                    else:
                        status = 200
                        estimated = counts is None
            except httpx.TimeoutException:
                code = "provider_timeout"
                status = 504
            except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                code = "invalid_provider_response" if received_success else "provider_error"
            except httpx.RequestError:
                code = "provider_error"
            if code is not None and aggregate is not None and aggregate.retry_on_failure:
                await cool_failed_model(service, aggregate, model)
            if code in ("provider_error", "provider_timeout") and index + 1 < len(attempts):
                await record(db, request, key, model, aggregate, status,
                       round((perf_counter() - attempt_started) * 1000),
                       0, None, None, code, attempt_failure=True,
                       provider_status=provider_status)
                continue
            break
        if code:
            if code != "provider_timeout":
                status = 502
            # If an upstream 2xx response has no usable usage, conservatively charge
            # the reservation rather than allowing unlimited unmetered calls.
            charged = cost if code in ("invalid_provider_usage", "invalid_provider_response") else 0
            billed = reservation.cents if charged else 0
            await service.settle(reservation, charged, billed)
            await record(db, request, key, model, aggregate, status,
                   round((perf_counter() - started) * 1000),
                   charged, None, None, code, billed, provider_status=provider_status)
            return error(status, code, code)
        actual = counts[0] if counts else cost
        billed = charge(model, counts[1] if counts else None,
                        counts[2] if counts else None, reservation.cents)
        await service.settle(reservation, actual, billed)
        await record(db, request, key, model, aggregate, status,
               round((perf_counter() - started) * 1000), actual,
               counts[1] if counts else None, counts[2] if counts else None, None, billed,
               reasoning_tokens=reasoning_count(raw_payload, protocol) if counts else None)
        return JSONResponse(payload, headers=(
            {"X-Gateway-Usage-Estimated": "true"} if estimated else None
        ))
    except asyncio.CancelledError:
        if reservation is not None and not (kind == "chat" and body["stream"]):
            with CancelScope(shield=True):
                await service.settle(
                    reservation, reservation.tokens if sent_upstream else 0,
                    reservation.cents if sent_upstream else 0,
                )
                if sent_upstream:
                    await record(db, request, key, model, aggregate, 499,
                                 round((perf_counter() - started) * 1000),
                                 reservation.tokens, None, None, "client_disconnected",
                                 reservation.cents)
        raise
    except HTTPException as exc:
        if reservation is not None and str(exc.detail).endswith("concurrency_exceeded"):
            await service.settle(reservation, 0, 0)
            return error(exc.status_code, str(exc.detail), str(exc.detail))
        raise
    except RedisError as exc:
        unavailable(exc)
    finally:
        if not deferred_close:
            with CancelScope(shield=True):
                await service.close()


@gateway_router.post("/chat/completions")
async def chat_completions(body: ChatBody, request: Request, db: Session = Depends(get_db),
                           key: ApiKey = Depends(authenticate),
                           x_queue_ticket: str | None = Header(default=None)) -> Response:
    return await forward(request, body.model_dump(), "chat", db, key, x_queue_ticket)


@gateway_router.post("/embeddings")
async def embeddings(body: EmbeddingBody, request: Request, db: Session = Depends(get_db),
                     key: ApiKey = Depends(authenticate),
                     x_queue_ticket: str | None = Header(default=None)) -> Response:
    if not body.input or isinstance(body.input, list) and (
        not body.input or any(not isinstance(value, str) or not value for value in body.input)
    ):
        return error(400, "invalid_input", "Input cannot be empty.")
    return await forward(request, body.model_dump(), "embedding", db, key, x_queue_ticket)


@gateway_router.post("/rerank")
async def rerank(body: RerankBody, request: Request, db: Session = Depends(get_db),
                 key: ApiKey = Depends(authenticate),
                 x_queue_ticket: str | None = Header(default=None)) -> Response:
    if any(not text for text in body.documents):
        return error(400, "invalid_input", "Documents cannot be empty.")
    if body.top_n is not None and body.top_n > len(body.documents):
        return error(400, "invalid_input", "top_n exceeds document count.")
    return await forward(request, body.model_dump(exclude_none=True), "rerank", db, key,
                         x_queue_ticket)


@gateway_router.post("/ocr")
async def ocr(body: OcrBody, request: Request, db: Session = Depends(get_db),
              key: ApiKey = Depends(authenticate),
              x_queue_ticket: str | None = Header(default=None)) -> Response:
    return await forward(request, body.model_dump(), "ocr", db, key, x_queue_ticket)


@gateway_router.post("/images/generations")
async def images(body: ImageBody, request: Request, db: Session = Depends(get_db),
                 key: ApiKey = Depends(authenticate),
                 x_queue_ticket: str | None = Header(default=None)) -> Response:
    return await forward(request, body.model_dump(), "image", db, key, x_queue_ticket)
