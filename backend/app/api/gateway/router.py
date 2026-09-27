from __future__ import annotations

# ruff: noqa: B008
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from itertools import count
from time import perf_counter
from typing import Any
from uuid import uuid4

import httpx
from anyio import CancelScope
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AggregatedModel,
    ApiKey,
    Organization,
    Project,
    Provider,
    ProviderModel,
    ProviderProtocol,
    ProviderSecret,
    RequestLog,
    UsageRecord,
    User,
)
from app.db.session import get_db
from app.modules.gateway.adapters import normalize, prepare, usage_counts
from app.modules.gateway.limits import Limiter, limiter, unavailable
from app.modules.gateway.streaming import StreamUsage, events, translate
from app.modules.model.playground import read_key
from app.modules.routing.strategies import choose_model

gateway_router = APIRouter(tags=["Gateway API"])
rounds = count()


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


def authenticate(request: Request, db: Session = Depends(get_db)) -> ApiKey:
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
    else:
        raise HTTPException(401, "invalid_api_key")
    if key.organization_id is not None:
        org = db.get(Organization, key.organization_id)
        if org is None or org.status != 1 or org.deleted_at is not None:
            raise HTTPException(403, "organization_forbidden")
    return key


def authorized_models(db: Session, key: ApiKey, model_name: str,
                      model_types: tuple[str, ...]) -> tuple[ProviderModel, AggregatedModel | None]:
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
            round_robin_index=next(rounds), fallback_model_id=aggregate.fallback_model_id,
        )
        selected = candidates.get(selection["selected_model_id"])
        if selected:
            return selected, aggregate
    raise HTTPException(403, "model_not_allowed")


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


def record(db: Session, request: Request, key: ApiKey, model: ProviderModel,
           aggregate: AggregatedModel | None, status: int, latency: int, tokens: int,
           input_tokens: int | None, output_tokens: int | None, error_code: str | None) -> None:
    log = RequestLog(
        request_id=f"req_{uuid4().hex}", organization_id=key.organization_id,
        project_id=key.project_id, api_key_id=key.id,
        aggregate_model_id=aggregate.id if aggregate else None,
        provider_id=model.provider_id, provider_model_id=model.id,
        public_model_name=aggregate.public_model_name if aggregate else model.access_model_code,
        model_type=model.model_type, endpoint=request.url.path, requester_ip=(
            request.client.host if request.client else "unknown"),
        http_status=status, latency_ms=latency, error_code=error_code,
    )
    db.add(log)
    db.flush()
    if tokens:
        db.add(UsageRecord(
            request_log_id=log.id, organization_id=key.organization_id,
            project_id=key.project_id, api_key_id=key.id,
            aggregate_model_id=aggregate.id if aggregate else None,
            provider_id=model.provider_id, provider_model_id=model.id,
            model_type=model.model_type, input_tokens=input_tokens,
            output_tokens=output_tokens, total_tokens=tokens,
        ))
    db.commit()


@gateway_router.get("/models")
async def list_models(db: Session = Depends(get_db), key: ApiKey = Depends(authenticate)) -> dict:
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
        await service.client.aclose()
    if not position:
        raise HTTPException(404, "queue_ticket_not_found")
    return {"ticket": ticket, "position": position, "status": "waiting"}


async def stream_response(
    request: Request, db: Session, key: ApiKey, model: ProviderModel,
    aggregate: AggregatedModel | None, service: Limiter, reservation,
    protocol: str, url: str, headers: dict, upstream_body: dict, timeout: float,
    public_name: str,
) -> Response:
    started = perf_counter()
    client = httpx.AsyncClient(timeout=timeout, trust_env=False)
    try:
        upstream = await client.send(client.build_request(
            "POST", url, headers=headers, json=upstream_body,
        ), stream=True)
    except (httpx.RequestError, httpx.TimeoutException) as exc:
        await client.aclose()
        await service.settle(reservation, 0)
        status = 504 if isinstance(exc, httpx.TimeoutException) else 502
        code = "provider_timeout" if status == 504 else "provider_error"
        record(db, request, key, model, aggregate, status,
               round((perf_counter() - started) * 1000), 0, None, None, code)
        return error(status, code, code)
    except asyncio.CancelledError:
        with CancelScope(shield=True):
            await client.aclose()
            await service.settle(reservation, reservation.tokens)
            record(db, request, key, model, aggregate, 499,
                   round((perf_counter() - started) * 1000), reservation.tokens,
                   None, None, "client_disconnected")
        raise
    if upstream.status_code >= 400 or upstream.is_redirect:
        await upstream.aclose()
        await client.aclose()
        await service.settle(reservation, 0)
        record(db, request, key, model, aggregate, 502,
               round((perf_counter() - started) * 1000), 0, None, None, "provider_error")
        return error(502, "provider_error", "provider_error")
    if "text/event-stream" not in upstream.headers.get("content-type", "").lower():
        await upstream.aclose()
        await client.aclose()
        await service.settle(reservation, reservation.tokens)
        record(db, request, key, model, aggregate, 502,
               round((perf_counter() - started) * 1000), reservation.tokens,
               None, None, "invalid_provider_stream")
        return error(502, "invalid_provider_stream", "invalid_provider_stream")

    async def chunks():
        usage = StreamUsage()
        status, code = 200, None
        try:
            async for event, data in events(upstream):
                fragment = translate(protocol, event, data, public_name, usage)
                if fragment:
                    yield fragment
                if usage.completed:
                    break
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
                await upstream.aclose()
                await client.aclose()
                try:
                    actual = (
                        usage.total if usage.completed and usage.total is not None
                        else reservation.tokens
                    )
                    await service.settle(reservation, actual)
                    record(db, request, key, model, aggregate, status,
                           round((perf_counter() - started) * 1000), actual,
                           usage.input_tokens if usage.completed else None,
                           usage.output_tokens if usage.completed else None, code)
                finally:
                    await service.client.aclose()
        if status == 200 and usage.completed:
            yield b"data: [DONE]\n\n"

    return StreamingResponse(
        chunks(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


async def forward(request: Request, body: dict, kind: str, db: Session, key: ApiKey,
                  ticket: str | None) -> Response:
    if len(json.dumps(body).encode()) > 262144:
        return error(413, "request_too_large", "Request body exceeds 256 KB.")
    model, aggregate = authorized_models(db, key, body["model"], MODEL_TYPES[kind])
    cost = token_estimate(body, kind)
    digest = fingerprint(body)
    service: Limiter = limiter()
    reservation = None
    deferred_close = False
    try:
        if key.wait_mode == "queue":
            state, rank, token, reservation = await service.admit(key, cost, digest, ticket)
        else:
            if ticket:
                return error(400, "invalid_ticket", "This key does not support queue tickets.")
            state, rank, token, reservation = await service.wait(key, cost, digest)
        if state == "queued":
            return JSONResponse(
                {"ticket": token, "position": rank, "status": "waiting",
                 "poll_url": f"/v1/queue/{token}", "retry_after_ms": 1000},
                status_code=202, headers={"Retry-After": "1"},
            )
        if state != "admitted":
            code = {"quota": "quota_exceeded", "too_large": "tpm_exceeded",
                    "invalid_ticket": "invalid_ticket"}.get(state, "rate_limit_exceeded")
            return error(400 if state == "invalid_ticket" else 429, code, code)
        assert reservation is not None
        try:
            db.expire_all()
            key = authenticate(request, db)
            model, aggregate = authorized_models(
                db, key, body["model"], MODEL_TYPES[kind],
            )
            protocol, base, secret, timeout = connection(db, model)
            url, headers, upstream_body = prepare(
                protocol, base, model.provider_model_name, secret, body, kind,
            )
            if kind == "chat" and body["stream"] and protocol in ("openai", "openai_compatible"):
                upstream_body["stream_options"] = {"include_usage": True}
        except Exception:
            await service.settle(reservation, 0)
            raise
        if kind == "chat" and body["stream"]:
            response = await stream_response(
                request, db, key, model, aggregate, service, reservation,
                protocol, url, headers, upstream_body, timeout, body["model"],
            )
            deferred_close = isinstance(response, StreamingResponse)
            return response
        started = perf_counter()
        status, payload, code, estimated, received_success = 502, None, None, False, False
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                response = await client.post(url, headers=headers, json=upstream_body)
            if response.status_code >= 400 or response.is_redirect:
                code = "provider_error"
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
        if code:
            if code != "provider_timeout":
                status = 502
            # If an upstream 2xx response has no usable usage, conservatively charge
            # the reservation rather than allowing unlimited unmetered calls.
            charged = cost if code in ("invalid_provider_usage", "invalid_provider_response") else 0
            await service.settle(reservation, charged)
            record(db, request, key, model, aggregate, status,
                   round((perf_counter() - started) * 1000),
                   charged, None, None, code)
            return error(status, code, code)
        actual = counts[0] if counts else cost
        await service.settle(reservation, actual)
        record(db, request, key, model, aggregate, status,
               round((perf_counter() - started) * 1000), actual,
               counts[1] if counts else None, counts[2] if counts else None, None)
        return JSONResponse(payload, headers=(
            {"X-Gateway-Usage-Estimated": "true"} if estimated else None
        ))
    except RedisError as exc:
        unavailable(exc)
    finally:
        if not deferred_close:
            await service.client.aclose()


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
