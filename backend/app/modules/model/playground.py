from __future__ import annotations

import asyncio
import codecs
import ipaddress
import json
import re
import socket
from itertools import count
from time import perf_counter
from typing import Literal
from urllib.parse import quote

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.responses import success_response
from app.db.models import AggregatedModel, Provider, ProviderModel, ProviderProtocol, ProviderSecret, User
from app.db.session import get_db
from app.modules.identity.router import actor, require_platform
from app.modules.model.playground_history import SENSITIVE, finish_record, start_record
from app.modules.routing.strategies import choose_model

router = APIRouter(prefix="/playground", tags=["在线调试"])
rounds = count()


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=32000)


class ConnectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["access", "aggregate", "custom"]
    model_id: int | None = Field(default=None, gt=0)
    custom_protocol: Literal["openai", "openai_compatible", "claude", "anthropic", "gemini"] | None = None
    custom_base_url: HttpUrl | None = Field(default=None, max_length=2048)
    custom_model_name: str | None = Field(default=None, max_length=128)
    custom_api_key: str | None = Field(default=None, max_length=4096)

    @model_validator(mode="after")
    def validate_connection(self):
        if self.source == "custom":
            if self.model_id is not None or not self.custom_protocol or not self.custom_base_url \
                    or not self.custom_model_name or not self.custom_model_name.strip():
                raise ValueError("自定义模型须填写协议、Base URL 和模型名称，且不能传模型 ID。")
            if self.custom_api_key is not None and not self.custom_api_key.strip():
                raise ValueError("API Key 不能为空白字符。")
        elif self.model_id is None or any(
            value is not None for value in (
                self.custom_protocol, self.custom_base_url, self.custom_model_name, self.custom_api_key)
        ):
            raise ValueError("已配置模型只能传模型 ID，不能混用自定义连接配置。")
        return self


class DebugRequest(ConnectionRequest):
    messages: list[Message] = Field(min_length=1, max_length=101)
    system_prompt: str = Field(default="", max_length=32000)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, gt=0, le=1)
    max_tokens: int | None = Field(default=None, ge=1, le=32768)
    stop: list[str] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def validate_messages(self):
        if self.messages[-1].role != "user":
            raise ValueError("最后一条消息必须是用户消息。")
        if any(not message.content.strip() for message in self.messages):
            raise ValueError("消息不能为空。")
        if any(not value or len(value) > 128 for value in self.stop):
            raise ValueError("停止词不能为空且每条不超过 128 字符。")
        return self


HEADER_NAME = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]+$")
BLOCKED_HEADERS = {
    "host", "content-length", "connection", "transfer-encoding", "upgrade",
    "te", "trailer", "keep-alive", "accept-encoding", "cookie",
}


class RawRequest(ConnectionRequest):
    body: dict = Field(max_length=100)
    headers: dict[str, str] = Field(default_factory=dict, max_length=40)
    stream: bool = False

    @model_validator(mode="after")
    def validate_headers(self):
        for name, value in self.headers.items():
            if not HEADER_NAME.fullmatch(name) or name.lower() in BLOCKED_HEADERS \
                    or name.lower().startswith("proxy-") or not isinstance(value, str) \
                    or len(value) > 4096 or "\r" in value or "\n" in value:
                raise ValueError("包含不允许发送的请求头。")
        if len(json.dumps(self.body, ensure_ascii=False)) > 262144:
            raise ValueError("请求体不能超过 256 KB。")
        return self


def resolve_model(db: Session, payload: ConnectionRequest) -> ProviderModel:
    if payload.source == "access":
        model = db.get(ProviderModel, payload.model_id)
    else:
        aggregate = db.get(AggregatedModel, payload.model_id)
        if aggregate is None or aggregate.status != 1 or aggregate.model_type != "llm":
            raise HTTPException(422, "聚合模型不可用于对话调试。")
        ids = aggregate.routing_model_ids or []
        candidates = {item.id: item for item in (
            db.get(ProviderModel, model_id) for model_id in ids + (
                [aggregate.fallback_model_id] if aggregate.fallback_model_id else [])
        ) if item is not None and item.model_type == "llm"}
        if len(candidates) != len(set(ids + (
            [aggregate.fallback_model_id] if aggregate.fallback_model_id else []))):
            raise HTTPException(422, "聚合模型候选配置不完整。")
        if aggregate.default_routing_strategy not in ("single", "round_robin", "least_latency"):
            raise HTTPException(422, "该聚合模型尚未配置内置路由策略。")
        # No live latency measurements are stored yet; choose the first available candidate.
        latencies = {model_id: index for index, model_id in enumerate(ids)}
        selection = choose_model(
            aggregate.default_routing_strategy, ids, candidates,
            round_robin_index=next(rounds), latencies=latencies,
            fallback_model_id=aggregate.fallback_model_id,
        )
        model = candidates.get(selection["selected_model_id"])
    if model is None or model.status != 1 or model.model_type != "llm":
        raise HTTPException(422, "没有可用的 LLM 接入模型。")
    return model


async def validate_custom_url(url: HttpUrl) -> None:
    if url.scheme != "https" or not url.host or url.username or url.password \
            or url.port not in (None, 443) or url.query or url.fragment:
        raise HTTPException(422, "自定义 Base URL 只能使用公网 HTTPS 地址（443 端口）。")
    host = url.host.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local") \
            or host.endswith(".internal"):
        raise HTTPException(422, "自定义 Base URL 不允许指向本机或内网。")
    try:
        addresses = await asyncio.to_thread(socket.getaddrinfo, host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise HTTPException(422, "自定义 Base URL 域名无法解析。") from exc
    if not addresses or any(
        not ipaddress.ip_address(address[4][0]).is_global for address in addresses
    ):
        raise HTTPException(422, "自定义 Base URL 不允许指向本机或内网。")


def read_key(secret: ProviderSecret | None) -> str | None:
    if secret is None:
        return None
    key = get_settings().provider_encryption_key
    if not key:
        raise HTTPException(503, "未配置供应商密钥加密密钥。")
    try:
        return Fernet(key.encode()).decrypt(secret.ciphertext.encode()).decode()
    except (ValueError, InvalidToken) as exc:
        raise HTTPException(503, "供应商密钥无法解密。") from exc


def endpoint_url(protocol: str, base: str, model_name: str, stream: bool = False) -> str:
    base = base.rstrip("/")
    if protocol in ("openai", "openai_compatible"):
        return f"{base}/chat/completions" if base.endswith("/v1") else f"{base}/v1/chat/completions"
    if protocol in ("claude", "anthropic"):
        return f"{base}/messages" if base.endswith("/v1") else f"{base}/v1/messages"
    if protocol == "gemini":
        prefix = base if base.endswith("/v1beta") else f"{base}/v1beta"
        action = "streamGenerateContent?alt=sse" if stream else "generateContent"
        return f"{prefix}/models/{quote(model_name, safe='')}:{action}"
    raise HTTPException(422, "暂不支持该模型协议。")


def build_request(protocol: str, base: str, model_name: str, key: str | None,
                  payload: DebugRequest, stream: bool = False) -> tuple[str, dict, dict]:
    messages = [message.model_dump() for message in payload.messages]
    system = payload.system_prompt.strip()
    if protocol in ("openai", "openai_compatible"):
        body = {"model": model_name, "messages": (
            [{"role": "system", "content": system}] if system else []) + messages, "stream": stream}
        body.update({name: value for name, value in (
            ("temperature", payload.temperature), ("top_p", payload.top_p),
            ("max_tokens", payload.max_tokens), ("stop", payload.stop or None),
        ) if value is not None})
        return endpoint_url(protocol, base, model_name, stream), {
            "Authorization": f"Bearer {key}"} if key else {}, body
    if protocol in ("claude", "anthropic"):
        body = {"model": model_name, "messages": messages, "max_tokens": payload.max_tokens or 1024,
                "stream": stream}
        body.update({name: value for name, value in (
            ("system", system or None), ("temperature", payload.temperature),
            ("top_p", payload.top_p), ("stop_sequences", payload.stop or None),
        ) if value is not None})
        headers = {"anthropic-version": "2023-06-01"}
        if key:
            headers["x-api-key"] = key
        return endpoint_url(protocol, base, model_name, stream), headers, body
    if protocol == "gemini":
        body = {"contents": [{"role": "model" if message["role"] == "assistant" else "user",
                              "parts": [{"text": message["content"]}]} for message in messages]}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        config = {name: value for name, value in (
            ("temperature", payload.temperature), ("topP", payload.top_p),
            ("maxOutputTokens", payload.max_tokens), ("stopSequences", payload.stop or None),
        ) if value is not None}
        if config:
            body["generationConfig"] = config
        return endpoint_url(protocol, base, model_name, stream), {
            "x-goog-api-key": key} if key else {}, body
    raise HTTPException(422, "暂不支持该模型协议。")


def parse_response(protocol: str, result: dict) -> tuple[str, dict]:
    if protocol in ("openai", "openai_compatible"):
        content = result["choices"][0]["message"]["content"]
        text = content if isinstance(content, str) else "".join(
            part.get("text", "") for part in content if isinstance(part, dict))
        usage = result.get("usage") or {}
        return text, {"input_tokens": usage.get("prompt_tokens"),
                      "output_tokens": usage.get("completion_tokens"),
                      "total_tokens": usage.get("total_tokens")}
    if protocol in ("claude", "anthropic"):
        usage = result.get("usage") or {}
        return "".join(part.get("text", "") for part in result["content"] if part.get("type") == "text"), {
            "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
            "total_tokens": (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0)}
    usage = result.get("usageMetadata") or {}
    return "".join(part.get("text", "") for part in result["candidates"][0]["content"]["parts"]), {
        "input_tokens": usage.get("promptTokenCount"), "output_tokens": usage.get("candidatesTokenCount"),
        "total_tokens": usage.get("totalTokenCount")}


async def prepare_connection(db: Session, payload: ConnectionRequest) -> tuple[str, str, str, str | None, str, float]:
    if payload.source == "custom":
        assert payload.custom_base_url is not None
        assert payload.custom_protocol is not None
        assert payload.custom_model_name is not None
        await validate_custom_url(payload.custom_base_url)
        model_name = payload.custom_model_name.strip()
        return (payload.custom_protocol, str(payload.custom_base_url), model_name,
                payload.custom_api_key.strip() if payload.custom_api_key else None, model_name, 60)
    model = resolve_model(db, payload)
    provider = db.get(Provider, model.provider_id)
    protocol = db.get(ProviderProtocol, model.protocol_id) if model.protocol_id else None
    secret = db.get(ProviderSecret, model.secret_id) if model.secret_id else None
    if provider is None or provider.status != 1 or protocol is None or protocol.status != 1 \
            or protocol.provider_id != model.provider_id:
        raise HTTPException(422, "模型所属供应商或协议不可用。")
    if model.secret_id and (secret is None or secret.status != 1 or secret.provider_id != model.provider_id):
        raise HTTPException(422, "模型密钥不可用。")
    return (protocol.protocol_type, model.base_url or protocol.base_url or provider.base_url,
            model.provider_model_name, read_key(secret), model.access_model_code,
            (model.timeout_ms or 60000) / 1000)


@router.post("/chat")
async def debug_chat(payload: DebugRequest, db: Session = Depends(get_db),
                     user: User = Depends(actor)) -> dict:
    require_platform(user)
    protocol_type, base, name, key, model_code, timeout = await prepare_connection(db, payload)
    url, headers, body = build_request(protocol_type, base, name, key, payload)
    record = start_record(db, user.id, "conversation", payload.source, model_code,
                          protocol_type, False, url, {"Content-Type": "application/json", **headers}, body, key)
    started = perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            response = await client.post(url, headers=headers, json=body)
        response.raise_for_status()
        text, usage = parse_response(protocol_type, response.json())
        if not text.strip():
            raise HTTPException(502, "上游模型没有返回文本内容。")
    except httpx.TimeoutException as exc:
        finish_record(db, record, 504, "上游模型响应超时。", round((perf_counter() - started) * 1000), key)
        raise HTTPException(504, "上游模型响应超时。") from exc
    except httpx.HTTPStatusError as exc:
        finish_record(db, record, exc.response.status_code, exc.response.text,
                      round((perf_counter() - started) * 1000), key)
        raise HTTPException(502, f"上游模型返回 HTTP {exc.response.status_code}。") from exc
    except HTTPException as exc:
        finish_record(db, record, exc.status_code, exc.detail,
                      round((perf_counter() - started) * 1000), key)
        raise
    except (httpx.RequestError, ValueError, KeyError, IndexError, TypeError) as exc:
        finish_record(db, record, 502, "上游模型请求失败或响应格式异常。",
                      round((perf_counter() - started) * 1000), key)
        raise HTTPException(502, "上游模型请求失败或响应格式异常。") from exc
    finish_record(db, record, response.status_code, response.text,
                  round((perf_counter() - started) * 1000), key)
    return success_response({
        "content": text, "usage": usage, "latency_ms": round((perf_counter() - started) * 1000),
        "access_model_code": model_code, "protocol": protocol_type,
    }).model_dump()


def auth_headers(protocol: str, key: str | None) -> dict[str, str]:
    if not key:
        return {}
    if protocol in ("openai", "openai_compatible"):
        return {"Authorization": f"Bearer {key}"}
    return {"x-goog-api-key": key} if protocol == "gemini" else {"x-api-key": key}


async def forward_request(url: str, headers: dict, body: dict, timeout: float, stream: bool,
                          model_code: str, protocol: str, db: Session, user_id: int,
                          source: str, mode: str, key: str | None):
    client = httpx.AsyncClient(timeout=timeout, trust_env=False)
    started = perf_counter()
    request = client.build_request("POST", url, headers=headers, json=body)
    secrets = ([key] if key else []) + [
        value for header, value in request.headers.items() if SENSITIVE.search(header)
    ]
    record = start_record(db, user_id, mode, source, model_code, protocol, stream,
                          url, dict(request.headers), body, secrets)
    try:
        upstream = await client.send(request, stream=True)
    except (httpx.TimeoutException, httpx.RequestError) as exc:
        await client.aclose()
        finish_record(db, record, 504 if isinstance(exc, httpx.TimeoutException) else 502,
                      "上游模型连接失败。", round((perf_counter() - started) * 1000), secrets)
        raise HTTPException(504 if isinstance(exc, httpx.TimeoutException) else 502,
                            "上游模型响应超时。" if isinstance(exc, httpx.TimeoutException)
                            else "上游模型连接失败。") from exc
    metadata = {"X-Playground-Model": quote(model_code, safe=""), "X-Playground-Protocol": protocol,
                "X-Playground-Latency-Ms": str(round((perf_counter() - started) * 1000))}
    if upstream.status_code >= 400 or upstream.is_redirect:
        try:
            content = (await upstream.aread()).decode("utf-8", errors="replace")
            finish_record(db, record, upstream.status_code, content,
                          round((perf_counter() - started) * 1000), secrets)
            return PlainTextResponse(content[:262144], status_code=upstream.status_code, headers=metadata)
        except (httpx.RequestError, httpx.TimeoutException) as exc:
            finish_record(db, record, 502, "读取上游响应失败。",
                          round((perf_counter() - started) * 1000), secrets)
            raise HTTPException(502, "读取上游响应失败。") from exc
        finally:
            await upstream.aclose()
            await client.aclose()
    if not stream:
        try:
            content = await upstream.aread()
            finish_record(db, record, upstream.status_code, content.decode("utf-8", errors="replace"),
                          round((perf_counter() - started) * 1000), secrets)
            return PlainTextResponse(content.decode("utf-8", errors="replace"),
                                     status_code=upstream.status_code, headers=metadata)
        except (httpx.RequestError, httpx.TimeoutException) as exc:
            finish_record(db, record, 502, "读取上游响应失败。",
                          round((perf_counter() - started) * 1000), secrets)
            raise HTTPException(502, "读取上游响应失败。") from exc
        finally:
            await upstream.aclose()
            await client.aclose()

    async def chunks():
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        parts: list[str] = []
        remaining = 262144
        status = upstream.status_code
        try:
            async for chunk in upstream.aiter_bytes():
                decoded = decoder.decode(chunk)
                if len(decoded) > remaining:
                    record.truncated = True
                if remaining > 0:
                    parts.append(decoded[:remaining])
                    remaining -= min(remaining, len(decoded))
                yield chunk
            parts.append(decoder.decode(b"", final=True)[:remaining])
        except (httpx.RequestError, httpx.TimeoutException):
            status = 502
            if remaining:
                parts.append("\nevent: playground_error\ndata: upstream stream interrupted\n\n"[:remaining])
            yield b"\nevent: playground_error\ndata: upstream stream interrupted\n\n"
        except asyncio.CancelledError:
            status = 499
            raise
        except GeneratorExit:
            status = 499
            raise
        finally:
            finish_record(db, record, status, "".join(parts),
                          round((perf_counter() - started) * 1000), secrets)
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        chunks(), media_type="text/event-stream", headers={
            **metadata, "Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no",
        })


@router.post("/chat/stream")
async def stream_chat(payload: DebugRequest, db: Session = Depends(get_db),
                      user: User = Depends(actor)):
    require_platform(user)
    protocol, base, name, key, model_code, timeout = await prepare_connection(db, payload)
    url, headers, body = build_request(protocol, base, name, key, payload, stream=True)
    return await forward_request(url, headers, body, timeout, True, model_code, protocol,
                                 db, user.id, payload.source, "conversation", key)


@router.post("/raw")
async def raw_request(payload: RawRequest, db: Session = Depends(get_db),
                      user: User = Depends(actor)):
    require_platform(user)
    protocol, base, name, key, model_code, timeout = await prepare_connection(db, payload)
    url = endpoint_url(protocol, base, name, payload.stream)
    headers = {**auth_headers(protocol, key), **payload.headers}
    if protocol in ("claude", "anthropic"):
        headers.setdefault("anthropic-version", "2023-06-01")
    body = {**payload.body}
    if protocol in ("openai", "openai_compatible", "claude", "anthropic"):
        body["stream"] = payload.stream
    return await forward_request(url, headers, body, timeout, payload.stream, model_code,
                                 protocol, db, user.id, payload.source, "raw", key)
