"""Per-worker clients and atomic, renewable upstream concurrency leases."""

import asyncio
import logging
from contextlib import suppress
from contextvars import ContextVar
from uuid import uuid4

import httpx
import redis.asyncio as redis
from anyio import CancelScope
from fastapi import HTTPException, Request
from starlette.responses import JSONResponse

from app.core.config import get_settings

logger = logging.getLogger(__name__)
current_runtime: ContextVar = ContextVar("gateway_runtime", default=None)


class RuntimeMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        app = scope.get("app")
        runtime = getattr(app.state, "gateway_runtime", None) if app else None
        if scope["type"] != "http" or runtime is None:
            return await self.app(scope, receive, send)
        settings = get_settings()
        guarded = (scope.get("method") == "POST"
                   and scope["path"].startswith(settings.gateway_api_prefix + "/"))
        if guarded and runtime.requests >= settings.gateway_max_concurrency:
            return await JSONResponse(
                {"error": {"code": "gateway_concurrency_exceeded",
                           "message": "Gateway is at capacity", "type": "gateway_error"}},
                status_code=503, headers={"Retry-After": "1"},
            )(scope, receive, send)
        token = current_runtime.set(runtime)
        if guarded:
            runtime.requests += 1
        try:
            await self.app(scope, receive, send)
        finally:
            if guarded:
                runtime.requests -= 1
            current_runtime.reset(token)

ACQUIRE = """
local now = tonumber(redis.call('TIME')[1]) * 1000
for i, key in ipairs(KEYS) do
    redis.call('ZREMRANGEBYSCORE', key, '-inf', now)
    if redis.call('ZCARD', key) >= tonumber(ARGV[i + 2]) then return 0 end
end
for _, key in ipairs(KEYS) do
    redis.call('ZADD', key, now + tonumber(ARGV[2]), ARGV[1])
    redis.call('PEXPIRE', key, ARGV[2])
end
return 1
"""

RENEW = """
for _, key in ipairs(KEYS) do
    if not redis.call('ZSCORE', key, ARGV[1]) then return 0 end
end
local now = tonumber(redis.call('TIME')[1]) * 1000
for _, key in ipairs(KEYS) do
    redis.call('ZADD', key, now + tonumber(ARGV[2]), ARGV[1])
    redis.call('PEXPIRE', key, ARGV[2])
end
return 1
"""

RELEASE = """
for _, key in ipairs(KEYS) do redis.call('ZREM', key, ARGV[1]) end
return 1
"""


class Runtime:
    def __init__(self):
        settings = get_settings()
        self.http = httpx.AsyncClient(
            trust_env=False,
            limits=httpx.Limits(max_connections=settings.http_max_connections,
                                max_keepalive_connections=settings.http_max_keepalive_connections),
        )
        self.redis = redis.from_url(
            settings.redis_url, decode_responses=False,
            max_connections=settings.redis_max_connections,
            socket_connect_timeout=2, socket_timeout=2,
        )
        self.active = 0
        self.requests = 0

    async def close(self):
        await self.http.aclose()
        await self.redis.aclose()


class BorrowedClient:
    def __init__(self, runtime: Runtime, service, keys: list[str], token: str,
                 ttl: int, owned: bool):
        self.runtime, self.service, self.keys, self.token = runtime, service, keys, token
        self.ttl, self.owned, self.closed = ttl, owned, False
        self.owner = asyncio.current_task()
        self.heartbeat = asyncio.create_task(self.renew())

    async def renew(self):
        try:
            while True:
                await asyncio.sleep(self.ttl / 3000)
                if not await self.service.client.eval(
                    RENEW, len(self.keys), *self.keys, self.token, self.ttl,
                ):
                    raise RuntimeError("Gateway concurrency lease lost")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Unable to renew upstream concurrency lease")
            # Stop upstream work instead of silently exceeding the configured limit.
            if self.owner:
                self.owner.cancel()

    def build_request(self, *args, **kwargs):
        return self.runtime.http.build_request(*args, **kwargs)

    async def send(self, *args, **kwargs):
        # StreamingResponse may consume the stream in a different task.
        self.owner = asyncio.current_task()
        return await self.runtime.http.send(*args, **kwargs)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.aclose()

    async def aclose(self):
        with CancelScope(shield=True):
            await self.release()

    async def release(self):
        if self.closed:
            return
        self.closed = True
        self.heartbeat.cancel()
        with suppress(asyncio.CancelledError):
            await self.heartbeat
        try:
            await self.service.client.eval(RELEASE, len(self.keys), *self.keys, self.token)
        finally:
            self.runtime.active -= 1
            if self.owned:
                await self.runtime.close()


async def upstream_client(request: Request, service, model) -> BorrowedClient:
    settings = get_settings()
    app = request.scope.get("app")
    runtime = getattr(app.state, "gateway_runtime", None) if app else None
    owned = runtime is None
    if owned:
        runtime = Runtime()
    if runtime.active >= settings.gateway_max_concurrency:
        if owned:
            await runtime.close()
        raise HTTPException(503, "gateway_concurrency_exceeded")
    runtime.active += 1
    keys = [f"gateway:concurrency:model:{model.id}",
            f"gateway:concurrency:provider:{model.provider_id}"]
    token, ttl = uuid4().hex, settings.gateway_lease_seconds * 1000
    try:
        admitted = await service.client.eval(
            ACQUIRE, len(keys), *keys, token, ttl,
            settings.gateway_model_concurrency, settings.gateway_provider_concurrency,
        )
        if not admitted:
            raise HTTPException(503, "upstream_concurrency_exceeded")
    except BaseException:
        with CancelScope(shield=True):
            # Also remove a lease if cancellation raced with the Redis response.
            try:
                await service.client.eval(RELEASE, len(keys), *keys, token)
            finally:
                runtime.active -= 1
                if owned:
                    await runtime.close()
        raise
    return BorrowedClient(runtime, service, keys, token, ttl, owned)
