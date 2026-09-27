import asyncio
import hashlib
import time
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
import httpx
from fastapi import Request
from fastapi.testclient import TestClient
from redis.exceptions import RedisError
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.gateway.router import ImageBody, stream_response, token_estimate
from app.db.base import Base
from app.db.models import (
    AggregatedModel,
    ApiKey,
    Organization,
    Project,
    Provider,
    ProviderModel,
    ProviderProtocol,
    RequestLog,
    UsageRecord,
    User,
)
from app.db.session import get_db
from app.main import app
from app.modules.gateway.limits import Limiter, period


@compiles(BigInteger, "sqlite")
def bigint_sqlite(_type, _compiler, **_kwargs):
    return "INTEGER"


@compiles(JSONB, "sqlite")
def jsonb_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


class GatewayTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine, tables=[
            User.__table__, Organization.__table__, Project.__table__, Provider.__table__,
            ProviderProtocol.__table__, ProviderModel.__table__, AggregatedModel.__table__,
            ApiKey.__table__, RequestLog.__table__, UsageRecord.__table__,
        ])
        self.db = Session(self.engine)
        self.raw = "agw_" + "a" * 40
        self.other_raw = "agw_" + "b" * 40
        self.db.add_all([
            User(id=1, username="admin", email="admin@example.com", password_hash="hash"),
            Project(id=1, name="Platform", code="platform", owner_user_id=1),
            Provider(id=1, name="Provider", code="provider", provider_type="openai",
                     base_url="https://example.com/v1"),
            ProviderProtocol(id=1, provider_id=1, code="openai", protocol_type="openai",
                             base_url="https://example.com/v1"),
            ProviderModel(id=1, provider_id=1, protocol_id=1, access_model_code="direct-chat",
                          provider_model_name="upstream-chat", model_type="llm"),
            ProviderModel(id=2, provider_id=1, protocol_id=1, access_model_code="direct-embed",
                          provider_model_name="upstream-embed", model_type="embedding"),
            AggregatedModel(id=1, aggregate_model_code="agg", public_model_name="public-chat",
                            model_type="llm", default_routing_strategy="single",
                            routing_model_ids=[1]),
            ApiKey(id=1, organization_id=None, project_id=1, scope_type="project",
                   name="Test", key_prefix=self.raw[:12],
                   key_hash=hashlib.sha256(self.raw.encode()).hexdigest(),
                   allowed_models={"aggregate_ids": [1], "access_ids": [1, 2]},
                   qps_limit=1, tpm_limit=100, token_budget=100,
                   budget_period="week", wait_mode="queue", max_wait_ms=2000, created_by=1),
            ApiKey(id=2, organization_id=None, user_id=1, scope_type="user",
                   name="Other", key_prefix=self.other_raw[:12],
                   key_hash=hashlib.sha256(self.other_raw.encode()).hexdigest(),
                   allowed_models={"aggregate_ids": [], "access_ids": [2]},
                   created_by=1, wait_mode="block", max_wait_ms=1000),
        ])
        self.db.commit()
        self.fake = fakeredis.aioredis.FakeRedis()
        self.limiter_patch = patch("app.api.gateway.router.limiter",
                                   side_effect=lambda: Limiter(self.fake))
        self.limiter_patch.start()
        self.calls = []
        self.bad_usage = False
        self.reply = None
        original = httpx.AsyncClient

        def upstream(request):
            self.calls.append(request)
            if self.reply is not None:
                return self.reply(request)
            body = request.read().decode()
            if "embeddings" in str(request.url):
                self.assertIn("upstream-embed", body)
                return httpx.Response(200, json={"object": "list", "data": [],
                                                  "usage": {"prompt_tokens": 3, "total_tokens": 3}})
            self.assertIn("upstream-chat", body)
            if self.bad_usage:
                return httpx.Response(200, json={"choices": []})
            return httpx.Response(200, json={
                "id": "response", "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
            })

        self.http_patch = patch(
            "app.api.gateway.router.httpx.AsyncClient",
            side_effect=lambda **kw: original(transport=httpx.MockTransport(upstream), **kw),
        )
        self.http_patch.start()
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.headers = {"Authorization": f"Bearer {self.raw}"}
        self.body = {"model": "public-chat", "messages": [{"role": "user", "content": "hello"}],
                     "max_tokens": 4}

    def tearDown(self):
        self.http_patch.stop()
        self.limiter_patch.stop()
        app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()

    def test_custom_prefix_authenticates_by_hash(self):
        raw = "team-prod_" + "c" * 40
        key = self.db.get(ApiKey, 1)
        key.custom_prefix = "team-prod"
        key.key_prefix = raw[:14]
        key.key_hash = hashlib.sha256(raw.encode()).hexdigest()
        self.db.commit()
        self.assertEqual(self.client.get("/v1/models", headers={
            "Authorization": f"Bearer {raw}",
        }).status_code, 200)
        self.assertEqual(self.client.post("/v1/chat/completions", json=self.body, headers={
            "x-api-key": raw,
        }).status_code, 200)
        self.assertEqual(self.client.get("/v1/models", headers=self.headers).status_code, 401)
        self.assertEqual(self.client.get("/v1/models", headers={
            "x-api-key": "some-other-prefix",
        }).status_code, 401)

    def test_auth_authorization_forward_and_usage(self):
        self.assertEqual(self.client.get("/v1/models").status_code, 401)
        self.assertEqual(self.client.get("/v1/models", headers={
            "x-api-key": self.raw}).json()["data"][0]["id"], "public-chat")
        self.assertEqual(self.client.post("/v1/chat/completions", json=self.body,
                                          headers=self.headers).json()["model"], "public-chat")
        self.assertEqual(self.db.query(UsageRecord).one().total_tokens, 5)
        self.assertEqual(self.db.query(RequestLog).one().api_key_id, 1)
        self.assertIsNone(self.db.query(RequestLog).one().organization_id)
        denied = self.client.post("/v1/chat/completions", json=self.body, headers={
            "Authorization": f"Bearer {self.other_raw}"})
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(len(self.calls), 1)
        key = self.db.get(ApiKey, 1)
        key.qps_limit = None
        self.db.commit()
        self.reply = lambda _request: httpx.Response(
            200, headers={"content-type": "text/event-stream"},
            content=b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
                    b'data: {"choices":[],"usage":{"prompt_tokens":2,'
                    b'"completion_tokens":1,"total_tokens":3}}\n\n'
                    b'data: [DONE]\n\n',
        )
        streamed = self.client.post(
            "/v1/chat/completions", json={**self.body, "stream": True}, headers=self.headers,
        )
        self.assertEqual(streamed.status_code, 200, streamed.text)
        self.assertIn('"content": "hi"', streamed.text)
        self.assertIn("data: [DONE]", streamed.text)
        self.assertEqual(self.db.query(UsageRecord).count(), 2)
        self.db.get(ApiKey, 1).status = 0
        self.db.commit()
        self.assertEqual(self.client.get("/v1/models", headers=self.headers).status_code, 401)

    def test_queue_position_ticket_binding_and_retry(self):
        key = self.db.get(ApiKey, 1)
        key.qps_limit = None
        key.tpm_limit = token_estimate({**self.body, "stream": False}, "chat") + 4
        self.db.commit()
        first = self.client.post("/v1/chat/completions", json=self.body, headers=self.headers)
        self.assertEqual(first.status_code, 200, first.text)
        queued = self.client.post("/v1/chat/completions", json=self.body, headers=self.headers)
        self.assertEqual(queued.status_code, 202, queued.text)
        ticket = queued.json()["ticket"]
        self.assertEqual(self.client.get(f"/v1/queue/{ticket}",
                                         headers=self.headers).json()["position"], 1)
        self.assertEqual(self.client.get(f"/v1/queue/{ticket}", headers={
            "x-api-key": self.other_raw}).status_code, 404)
        self.assertEqual(self.client.post("/v1/chat/completions", json={
            **self.body, "messages": [{"role": "user", "content": "changed"}],
        }, headers={**self.headers, "x-queue-ticket": ticket}).status_code, 400)
        self.assertEqual(self.client.post("/v1/chat/completions", json=self.body, headers={
            **self.headers, "x-queue-ticket": ticket}).status_code, 202)
        second = self.client.post("/v1/chat/completions", json=self.body, headers=self.headers)
        self.assertEqual(second.status_code, 202)
        self.assertEqual(second.json()["position"], 2)
        key.tpm_limit = 100
        self.db.commit()
        admitted = self.client.post("/v1/chat/completions", json=self.body, headers={
            **self.headers, "x-queue-ticket": ticket})
        self.assertEqual(admitted.status_code, 200, admitted.text)
        self.assertEqual(self.client.get(f"/v1/queue/{second.json()['ticket']}",
                                         headers=self.headers).json()["position"], 1)
        self.assertEqual(self.client.get(f"/v1/queue/{ticket}",
                                         headers=self.headers).status_code, 404)

    def test_budget_tpm_reconciliation_and_embedding(self):
        key = self.db.get(ApiKey, 1)
        key.qps_limit = None
        key.tpm_limit = 26
        key.token_budget = 26
        key.wait_mode = "block"
        self.db.commit()
        for _ in range(2):
            result = self.client.post("/v1/chat/completions", json=self.body, headers=self.headers)
            self.assertEqual(result.status_code, 200, result.text)
        key.token_budget = 12
        self.db.commit()
        self.assertEqual(self.client.post("/v1/chat/completions", json=self.body,
                                          headers=self.headers).status_code, 429)
        other = {"x-api-key": self.other_raw}
        embedded = self.client.post("/v1/embeddings",
                                    json={"model": "direct-embed", "input": "hello"},
                                    headers=other)
        self.assertEqual(embedded.status_code, 200, embedded.text)
        self.assertEqual(self.db.query(UsageRecord).count(), 3)

    def test_expired_and_disabled_owner(self):
        key = self.db.get(ApiKey, 1)
        key.expires_at = datetime(2020, 1, 1, tzinfo=UTC)
        self.db.commit()
        self.assertEqual(self.client.get("/v1/models", headers=self.headers).status_code, 401)
        self.db.get(User, 1).status = 0
        self.db.commit()
        self.assertEqual(self.client.get("/v1/models", headers={
            "x-api-key": self.other_raw}).status_code, 403)

    def test_period_boundaries(self):
        self.assertEqual(period(datetime(2026, 9, 27, tzinfo=UTC), "week")[0], "20260921")
        self.assertEqual(period(datetime(2026, 12, 31, tzinfo=UTC), "month")[0], "20261201")
        self.assertEqual(period(datetime(2027, 1, 1, tzinfo=UTC), "month")[0], "20270101")

    def test_fail_closed_and_missing_usage(self):
        self.bad_usage = True
        result = self.client.post("/v1/chat/completions", json=self.body, headers=self.headers)
        self.assertEqual(result.status_code, 502)
        self.assertGreater(self.db.query(UsageRecord).one().total_tokens, 0)
        self.fake.eval = AsyncMock(side_effect=RedisError("connection lost"))
        self.assertEqual(self.client.post("/v1/chat/completions", json=self.body,
                                          headers=self.headers).status_code, 503)
        self.assertEqual(len(self.calls), 1)

    def test_blocking_times_out_and_oversized_request(self):
        key = self.db.get(ApiKey, 1)
        key.wait_mode = "block"
        key.tpm_limit = 10
        self.db.commit()
        oversized = self.client.post("/v1/chat/completions", json=self.body,
                                     headers=self.headers)
        self.assertEqual(oversized.status_code, 429)
        key.tpm_limit = 100
        key.qps_limit = None
        self.db.commit()
        self.assertEqual(self.client.post("/v1/chat/completions", json=self.body,
                                          headers=self.headers).status_code, 200)
        key.tpm_limit = token_estimate(self.body, "chat") + 4
        key.max_wait_ms = 1000
        self.db.commit()
        next_window = Limiter(self.fake).keys(
            key, datetime.now(UTC) + timedelta(minutes=1),
        )[0][1]
        asyncio.run(self.fake.set(next_window, 5, ex=70))
        started = time.monotonic()
        blocked = self.client.post("/v1/chat/completions", json=self.body, headers=self.headers)
        self.assertEqual(blocked.status_code, 429)
        self.assertGreaterEqual(time.monotonic() - started, 1)

    def test_other_model_types_and_authorization(self):
        key = self.db.get(ApiKey, 1)
        key.qps_limit = None
        key.allowed_models = {"aggregate_ids": [1], "access_ids": [1, 2, 3, 4, 5, 6]}
        self.db.add_all([
            ProviderModel(id=index, provider_id=1, protocol_id=1,
                          access_model_code=name, provider_model_name=f"upstream-{name}",
                          model_type=kind)
            for index, name, kind in (
                (3, "reranker", "rerank"), (4, "reader", "ocr"),
                (5, "artist", "text_to_image"), (6, "vision", "vlm"),
            )
        ])
        self.db.commit()

        def upstream(request):
            path = request.url.path
            if path.endswith("/rerank"):
                return httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 0.9}]})
            if path.endswith("/ocr"):
                return httpx.Response(200, json={"text": "recognized"})
            if path.endswith("/images/generations"):
                return httpx.Response(200, json={"data": [{"url": "https://example.com/image"}]})
            self.assertIn('"type":"image_url"', request.read().decode())
            return httpx.Response(200, json={
                "choices": [{"message": {"content": "seen"}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 2, "total_tokens": 22},
            })

        self.reply = upstream
        calls = (
            ("/v1/rerank", {"model": "reranker", "query": "hello",
                            "documents": ["hello", "world"]}),
            ("/v1/ocr", {"model": "reader", "image_url": "https://example.com/input.png"}),
            ("/v1/images/generations", {"model": "artist", "prompt": "sunrise"}),
            ("/v1/chat/completions", {"model": "vision", "max_tokens": 6,
                                      "messages": [{"role": "user", "content": [
                                          {"type": "text", "text": "what is this"},
                                          {"type": "image_url", "image_url": {
                                              "url": "https://example.com/input.png",
                                          }},
                                      ]}]}),
        )
        for path, payload in calls:
            with self.subTest(path=path):
                result = self.client.post(path, json=payload, headers=self.headers)
                self.assertEqual(result.status_code, 200, result.text)
                self.assertEqual(result.json()["model"], payload["model"])
        self.assertEqual(self.db.query(UsageRecord).count(), 4)
        self.assertEqual(sum(item.total_tokens for item in self.db.query(UsageRecord)), 22 + sum(
            token_estimate(
                ImageBody.model_validate(payload).model_dump() if kind == "image" else payload,
                kind,
            ) for (_, payload), kind in zip(
                calls[:3], ("rerank", "ocr", "image"), strict=True,
            )
        ))
        self.assertEqual(self.client.post("/v1/rerank", json=calls[0][1], headers={
            "x-api-key": self.other_raw,
        }).status_code, 403)

    def test_claude_gemini_and_stream_accounting(self):
        key = self.db.get(ApiKey, 1)
        key.qps_limit = None
        key.tpm_limit = 200
        key.token_budget = 200
        key.allowed_models = {"aggregate_ids": [], "access_ids": [7, 8]}
        self.db.add_all([
            ProviderProtocol(id=2, provider_id=1, code="claude", protocol_type="anthropic",
                             base_url="https://example.com/v1"),
            ProviderProtocol(id=3, provider_id=1, code="gemini", protocol_type="gemini",
                             base_url="https://example.com/v1beta"),
            ProviderModel(id=7, provider_id=1, protocol_id=2, access_model_code="claude",
                          provider_model_name="claude-upstream", model_type="llm"),
            ProviderModel(id=8, provider_id=1, protocol_id=3, access_model_code="gemini",
                          provider_model_name="gemini-upstream", model_type="llm"),
        ])
        self.db.commit()

        def upstream(request):
            data = request.read().decode()
            if "messages" in str(request.url):
                self.assertIn("max_tokens", data)
                if '"stream":true' in data:
                    return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                          content=(
                                              'event: message_start\n'
                                              'data: {"message":{"usage":{"input_tokens":4}}}\n\n'
                                              'event: content_block_delta\n'
                                              'data: {"delta":{"type":"text_delta",'
                                              '"text":"hello"}}\n\n'
                                              'event: message_delta\n'
                                              'data: {"usage":{"output_tokens":2}}\n\n'
                                              'event: message_stop\n'
                                              'data: {"type":"message_stop"}\n\n'
                                          ).encode())
                return httpx.Response(200, json={
                    "id": "msg1", "content": [{"type": "text", "text": "claude reply"}],
                    "usage": {"input_tokens": 4, "output_tokens": 2},
                })
            self.assertTrue(str(request.url).endswith("generateContent")
                            or "streamGenerateContent" in str(request.url))
            if "streamGenerateContent" in str(request.url):
                return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                      content=(
                                          'data: {"candidates":[{"content":{"parts":'
                                          '[{"text":"hello"}]}}]}\n\n'
                                          'data: {"candidates":[{"content":{"parts":'
                                          '[{"text":"hello world"}]}}],"usageMetadata":'
                                          '{"promptTokenCount":3,"candidatesTokenCount":2,'
                                          '"totalTokenCount":5}}\n\n'
                                      ).encode())
            return httpx.Response(200, json={
                "candidates": [{"content": {"parts": [{"text": "gemini reply"}]}}],
                "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 2,
                                  "totalTokenCount": 5},
            })

        self.reply = upstream
        for name, expected, cost in (("claude", "claude reply", 6),
                                     ("gemini", "gemini reply", 5)):
            response = self.client.post(
                "/v1/chat/completions", json={**self.body, "model": name},
                headers=self.headers,
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["choices"][0]["message"]["content"], expected)
            self.assertEqual(response.json()["usage"]["total_tokens"], cost)
        for name in ("claude", "gemini"):
            response = self.client.post(
                "/v1/chat/completions", json={**self.body, "model": name, "stream": True},
                headers=self.headers,
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIn("data: [DONE]", response.text)
            self.assertIn('"content": "hello"', response.text)
        self.assertEqual([item.total_tokens for item in self.db.query(UsageRecord)], [6, 5, 6, 5])

    def test_incomplete_stream_charges_reservation(self):
        key = self.db.get(ApiKey, 1)
        key.qps_limit = None
        self.db.commit()
        self.reply = lambda _request: httpx.Response(
            200, headers={"content-type": "text/event-stream"},
            content=b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n',
        )
        response = self.client.post(
            "/v1/chat/completions", json={**self.body, "stream": True}, headers=self.headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("provider_stream_interrupted", response.text)
        self.assertNotIn("data: [DONE]", response.text)
        self.assertEqual(self.db.query(RequestLog).one().http_status, 502)
        self.assertEqual(self.db.query(UsageRecord).one().total_tokens,
                         token_estimate({**self.body, "stream": True}, "chat"))

    def test_malformed_provider_payload_is_metered(self):
        key = self.db.get(ApiKey, 1)
        key.qps_limit = None
        self.db.commit()
        self.reply = lambda _request: httpx.Response(
            200, json={"choices": [], "usage": "not an object"},
        )
        response = self.client.post("/v1/chat/completions", json=self.body,
                                    headers=self.headers)
        self.assertEqual(response.status_code, 502, response.text)
        self.assertEqual(response.json()["error"]["code"], "invalid_provider_response")
        self.assertEqual(self.db.query(UsageRecord).one().total_tokens,
                         token_estimate(self.body, "chat"))

    def test_disconnected_stream_is_metered(self):
        key = self.db.get(ApiKey, 1)
        key.qps_limit = None
        self.db.commit()
        self.reply = lambda _request: httpx.Response(
            200, headers={"content-type": "text/event-stream"},
            content=b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
                    b'data: [DONE]\n\n',
        )

        async def disconnect():
            service = Limiter(self.fake)
            cost = token_estimate({**self.body, "stream": True}, "chat")
            state, _, _, reservation = await service.admit(key, cost, "disconnect", None)
            self.assertEqual(state, "admitted")
            request = Request({"type": "http", "method": "POST", "scheme": "http",
                               "path": "/v1/chat/completions", "query_string": b"",
                               "headers": [], "server": ("testserver", 80),
                               "client": ("127.0.0.1", 1234)})
            response = await stream_response(
                request, self.db, key, self.db.get(ProviderModel, 1), None,
                service, reservation, "openai", "https://example.com/v1/chat/completions",
                {}, {**self.body, "stream": True}, 60, "public-chat",
            )
            self.assertIn(b"partial", await anext(response.body_iterator))
            await response.body_iterator.aclose()

        asyncio.run(disconnect())
        self.assertEqual(self.db.query(RequestLog).one().http_status, 499)
        self.assertEqual(self.db.query(UsageRecord).one().total_tokens,
                         token_estimate({**self.body, "stream": True}, "chat"))
