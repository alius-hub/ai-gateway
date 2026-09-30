import asyncio
import hashlib
import threading
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import fakeredis.aioredis
import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import BigInteger, create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.api.gateway.router import database_phase, gateway_router
from app.core.config import get_settings
from app.db.base import Base
from app.db.models import (
    ApiKey,
    GatewaySpend,
    Provider,
    ProviderModel,
    ProviderProtocol,
    RequestLog,
    UsageRecord,
    User,
)
from app.db.session import get_db
from app.modules.gateway.budgets import baselines, increment
from app.modules.gateway.limits import Limiter
from app.modules.gateway.runtime import (
    ACQUIRE,
    RELEASE,
    RENEW,
    Runtime,
    RuntimeMiddleware,
    current_runtime,
    upstream_client,
)


@compiles(BigInteger, "sqlite")
def bigint_sqlite(_type, _compiler, **_kwargs):
    return "INTEGER"


@compiles(JSONB, "sqlite")
def jsonb_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


@pytest.fixture
def database(tmp_path):
    # One physical connection: upstream concurrency must exceed DB pool capacity.
    engine = create_engine(
        f"sqlite:///{tmp_path / 'capacity.db'}", connect_args={"check_same_thread": False},
        pool_size=1, max_overflow=0, pool_timeout=1,
    )
    Base.metadata.create_all(engine)
    raw = "agw_capacity_test"
    with Session(engine) as db:
        db.add_all([
            User(id=1, username="test", email="test@example.com", password_hash="unused"),
            Provider(id=1, name="test", code="test", provider_type="openai",
                     base_url="https://provider.example/v1"),
            ProviderProtocol(id=1, provider_id=1, code="openai", protocol_type="openai",
                             base_url="https://provider.example/v1"),
            ProviderModel(id=1, provider_id=1, protocol_id=1, access_model_code="chat",
                          provider_model_name="chat", model_type="llm", currency="CNY",
                          input_price=Decimal("1"), output_price=Decimal("1")),
            ApiKey(id=1, user_id=1, scope_type="user", name="test", key_prefix="agw_",
                   key_hash=hashlib.sha256(raw.encode()).hexdigest(), created_by=1,
                   allowed_models={"access_ids": [1]}, wait_mode="block"),
        ])
        db.commit()
    try:
        yield engine, raw
    finally:
        engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_twenty_upstreams_share_one_database_connection(database, stream):
    engine, raw = database
    app = FastAPI()
    app.include_router(gateway_router, prefix="/v1")
    app.add_middleware(RuntimeMiddleware)

    def request_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = request_db
    runtime = Runtime()
    await runtime.redis.aclose()
    runtime.redis = fakeredis.aioredis.FakeRedis()
    await runtime.http.aclose()
    app.state.gateway_runtime = runtime
    reached, release = asyncio.Event(), asyncio.Event()
    arrived = 0
    loop_thread = threading.get_ident()
    sql_threads = []

    def sql(_conn, _cursor, _statement, _parameters, _context, _many):
        sql_threads.append(threading.get_ident())

    event.listen(engine, "before_cursor_execute", sql)

    async def wait_upstream():
        nonlocal arrived
        arrived += 1
        if arrived == 20:
            reached.set()
        await release.wait()

    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            await wait_upstream()
            yield (b'data: {"choices":[{"delta":{"content":"ok"}}],'
                   b'"usage":{"prompt_tokens":2,"completion_tokens":3,"total_tokens":5}}\n\n')
            yield b'data: [DONE]\n\n'

    async def upstream(_request):
        if stream:
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  stream=SlowStream())
        await wait_upstream()
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
        })

    runtime.http = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as client:
        tasks = [asyncio.create_task(client.post(
            "/v1/chat/completions", headers={"Authorization": f"Bearer {raw}"},
            json={"model": "chat", "messages": [{"role": "user", "content": "hello"}],
                  "max_tokens": 4, "stream": stream},
        )) for _ in range(20)]
        try:
            await asyncio.wait_for(reached.wait(), timeout=10)
            assert engine.pool.checkedout() == 0
            assert runtime.active == 20
            assert runtime.requests == 20

            def independent_query():
                with Session(engine) as db:
                    return db.get(User, 1).username

            assert await asyncio.to_thread(independent_query) == "test"
            release.set()
            responses = await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)
            assert all(response.status_code == 200 for response in responses)
            assert runtime.active == runtime.requests == 0
            assert await runtime.redis.zcard("gateway:concurrency:model:1") == 0
            assert sql_threads and loop_thread not in sql_threads
        finally:
            release.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await runtime.close()
    event.remove(engine, "before_cursor_execute", sql)
    with Session(engine) as db:
        assert len(db.scalars(select(RequestLog)).all()) == 20
        assert len(db.scalars(select(UsageRecord)).all()) == 20
        assert {row.spent_cents for row in db.scalars(select(GatewaySpend))} == {20}


@pytest.mark.asyncio
async def test_model_and_provider_limits_are_atomic_across_clients():
    server = fakeredis.FakeServer()
    first = fakeredis.aioredis.FakeRedis(server=server)
    second = fakeredis.aioredis.FakeRedis(server=server)
    model, provider = "gateway:concurrency:model:1", "gateway:concurrency:provider:1"
    try:
        assert await first.eval(ACQUIRE, 2, model, provider, "first", 120000, 1, 2) == 1
        assert await second.eval(ACQUIRE, 2, model, provider, "second", 120000, 1, 2) == 0
        assert await first.zcard(provider) == 1
        assert await second.eval(RENEW, 2, model, provider, "first", 120000) == 1
        await first.eval(RELEASE, 2, model, provider, "first")
        assert await second.eval(ACQUIRE, 2, model, provider, "second", 120000, 1, 1) == 1
        assert await first.eval(ACQUIRE, 2, "other-model", provider,
                                "third", 120000, 5, 1) == 0
        assert await first.zcard("other-model") == 0
        await first.delete(model)
        assert await second.eval(RENEW, 2, model, provider, "second", 120000) == 0
    finally:
        await first.aclose()
        await second.aclose()


@pytest.mark.asyncio
async def test_shared_clients_survive_request_release_and_reject_capacity():
    runtime = Runtime()
    await runtime.redis.aclose()
    runtime.redis = fakeredis.aioredis.FakeRedis()
    app = FastAPI()
    app.state.gateway_runtime = runtime
    request = Request({"type": "http", "app": app})
    settings = get_settings().model_copy(update={"gateway_model_concurrency": 1})
    token = current_runtime.set(runtime)
    service = Limiter(runtime.redis, shared=True)
    model = SimpleNamespace(id=1, provider_id=1)
    try:
        with patch("app.modules.gateway.runtime.get_settings", return_value=settings):
            client = await upstream_client(request, service, model)
            with pytest.raises(HTTPException, match="upstream_concurrency_exceeded"):
                await upstream_client(request, service, model)
            assert runtime.active == 1
            await client.aclose()
            await client.aclose()
            await service.close()
            assert not runtime.http.is_closed
            assert await runtime.redis.ping()
            again = await upstream_client(request, service, model)
            assert again.runtime.http is client.runtime.http
            await again.aclose()
            assert runtime.active == 0
    finally:
        current_runtime.reset(token)
        await runtime.close()
    assert runtime.http.is_closed


def test_incremental_totals_rollback_and_budget_changes(database):
    engine, _ = database
    now = datetime.now(UTC)
    with Session(engine) as db:
        key = db.get(ApiKey, 1)
        increment(db, key, 7, now)
        db.rollback()
        assert db.scalars(select(GatewaySpend)).all() == []
        key = db.get(ApiKey, 1)
        increment(db, key, 7, now)
        increment(db, key, 11, now)
        db.commit()
        key = db.get(ApiKey, 1)
        key.amount_budget, key.budget_period = Decimal("1"), "week"
        assert baselines(db, key, None) == (18, 0)
        key.budget_period = "month"
        assert baselines(db, key, None) == (18, 0)
        # Counter lookup never reads the growing usage table.
        statements = []
        event.listen(engine, "before_cursor_execute",
                     lambda _c, _u, sql, *_: statements.append(sql))
        database_phase(db, baselines, db, key, None)
        assert not any("usage_records" in sql.lower() for sql in statements)
        assert engine.pool.checkedout() == 0
