import asyncio
import base64
import hashlib
import io
import json
import tempfile
import time
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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

from app.api.gateway.router import ImageBody, cooldown_key, stream_response, token_estimate
from app.core.config import get_settings
from app.db.base import Base
from app.db.models import (
    AggregatedModel,
    ApiKey,
    GatewayLogSettings,
    Organization,
    Project,
    ProjectMember,
    Provider,
    ProviderModel,
    ProviderProtocol,
    RequestLog,
    UsageRecord,
    User,
)
from app.db.session import get_db
from app.main import app
from app.modules.audit.router import image_entries
from app.modules.gateway.adapters import reasoning_count, usage_counts
from app.modules.gateway.archive import CallArchive, _upload
from app.modules.gateway.limits import Limiter, period
from app.modules.gateway.pricing import cents as price_cents
from app.modules.identity.router import actor
from app.modules.model.router import AccessModelCreate


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
            User.__table__, Organization.__table__, Project.__table__, ProjectMember.__table__,
            Provider.__table__,
            ProviderProtocol.__table__, ProviderModel.__table__, AggregatedModel.__table__,
            ApiKey.__table__, RequestLog.__table__, UsageRecord.__table__,
            GatewayLogSettings.__table__,
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
        disabled = get_settings().model_copy(update={"log_archive_enabled": False})
        self.archive_patch = patch("app.modules.gateway.archive.get_settings",
                                   return_value=disabled)
        self.audit_patch = patch("app.modules.audit.router.get_settings",
                                 return_value=disabled)
        self.archive_patch.start()
        self.audit_patch.start()
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.headers = {"Authorization": f"Bearer {self.raw}"}
        self.body = {"model": "public-chat", "messages": [{"role": "user", "content": "hello"}],
                     "max_tokens": 4}

    def tearDown(self):
        self.audit_patch.stop()
        self.archive_patch.stop()
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

    def test_assigned_project_key_requires_active_member(self):
        key = self.db.get(ApiKey, 1)
        key.user_id = 1
        self.db.commit()
        self.assertEqual(self.client.get("/v1/models", headers=self.headers).status_code, 403)
        member = ProjectMember(project_id=1, user_id=1, status=1)
        self.db.add(member)
        self.db.commit()
        self.assertEqual(self.client.get("/v1/models", headers=self.headers).status_code, 200)
        member.status = 0
        self.db.commit()
        self.assertEqual(self.client.get("/v1/models", headers=self.headers).status_code, 403)
        member.status = 1
        self.db.get(User, 1).status = 0
        self.db.commit()
        self.assertEqual(self.client.get("/v1/models", headers=self.headers).status_code, 403)
        key.user_id = None
        self.db.commit()
        self.assertEqual(self.client.get("/v1/models", headers=self.headers).status_code, 200)

    def test_project_budget_shared_across_keys_and_recovered_from_usage(self):
        model = self.db.get(ProviderModel, 1)
        model.input_price = Decimal("1.00")
        model.output_price = Decimal("1.00")
        self.db.get(Project, 1).amount_budget = Decimal("0.02")
        self.db.get(ApiKey, 1).qps_limit = None
        other = ApiKey(id=3, project_id=1, scope_type="project", name="Second",
                       key_prefix="agw_second", key_hash=hashlib.sha256(
                           b"agw_second_key").hexdigest(),
                       allowed_models={"aggregate_ids": [1], "access_ids": []},
                       wait_mode="block", max_wait_ms=1000, created_by=1)
        self.db.add(other)
        self.db.commit()
        first = self.client.post("/v1/chat/completions", json=self.body, headers=self.headers)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(self.db.query(UsageRecord).one().estimated_cost, Decimal("0.01"))
        second_headers = {"Authorization": "Bearer agw_second_key"}
        second = self.client.post("/v1/chat/completions", json=self.body, headers=second_headers)
        self.assertEqual(second.status_code, 200, second.text)
        denied = self.client.post("/v1/chat/completions", json=self.body, headers=self.headers)
        self.assertEqual(denied.status_code, 429)
        self.assertEqual(denied.json()["error"]["code"], "project_budget_exceeded")
        asyncio.run(self.fake.flushall())
        restored = self.client.post("/v1/chat/completions", json=self.body, headers=second_headers)
        self.assertEqual(restored.status_code, 429)

    def test_key_amount_quota_and_missing_price(self):
        key = self.db.get(ApiKey, 1)
        key.amount_budget = Decimal("0.04")
        key.qps_limit = None
        self.db.commit()
        missing = self.client.post("/v1/chat/completions", json=self.body, headers=self.headers)
        self.assertEqual(missing.status_code, 503)
        self.assertEqual(missing.json()["error"]["code"], "model_price_missing")
        model = self.db.get(ProviderModel, 1)
        model.input_price = Decimal("10")
        model.output_price = Decimal("10")
        self.db.commit()
        denied = self.client.post("/v1/chat/completions", json=self.body, headers=self.headers)
        self.assertEqual(denied.status_code, 429)
        self.assertEqual(denied.json()["error"]["code"], "amount_quota_exceeded")

    def test_price_round_half_up(self):
        model = self.db.get(ProviderModel, 1)
        model.price_unit_k = 1
        model.input_price = Decimal("5.00")
        model.output_price = Decimal("0.00")
        self.assertEqual(price_cents(model, 1, 0), 1)
        model.price_unit_k = 2
        self.assertEqual(price_cents(model, 1, 0), 0)

    def test_tiered_prices_select_input_and_output_independently(self):
        model = self.db.get(ProviderModel, 1)
        model.tiered_pricing = True
        model.input_price_tiers = [
            {"up_to_tokens": 10, "price": "10.00"},
            {"up_to_tokens": None, "price": "20.00"},
        ]
        model.output_price_tiers = [
            {"up_to_tokens": 3, "price": "30.00"},
            {"up_to_tokens": None, "price": "40.00"},
        ]
        self.assertEqual(price_cents(model, 10, 3), 19)
        self.assertEqual(price_cents(model, 11, 3), 31)
        self.assertEqual(price_cents(model, 10, 4), 26)
        model.tiered_pricing = False
        model.input_price, model.output_price = Decimal("1.00"), Decimal("1.00")
        self.assertEqual(price_cents(model, 10, 3), 1)

    def test_tiered_usage_settles_project_budget_at_actual_output_tier(self):
        model = self.db.get(ProviderModel, 1)
        model.tiered_pricing = True
        model.input_price_tiers = [{"up_to_tokens": None, "price": "1.00"}]
        model.output_price_tiers = [
            {"up_to_tokens": 4, "price": "1.00"},
            {"up_to_tokens": None, "price": "10.00"},
        ]
        self.db.get(Project, 1).amount_budget = Decimal("0.05")
        self.db.get(ApiKey, 1).qps_limit = None
        self.db.commit()
        self.reply = lambda _request: httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 5, "total_tokens": 7},
        })
        response = self.client.post("/v1/chat/completions", json=self.body, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.db.query(UsageRecord).one().estimated_cost, Decimal("0.05"))
        denied = self.client.post("/v1/chat/completions", json=self.body, headers=self.headers)
        self.assertEqual(denied.status_code, 429)
        self.assertEqual(denied.json()["error"]["code"], "project_budget_exceeded")

    def test_streaming_tiered_usage_uses_completed_token_counts(self):
        model = self.db.get(ProviderModel, 1)
        model.tiered_pricing = True
        model.input_price_tiers = [{"up_to_tokens": None, "price": "1.00"}]
        model.output_price_tiers = [
            {"up_to_tokens": 4, "price": "1.00"},
            {"up_to_tokens": None, "price": "10.00"},
        ]
        self.db.get(ApiKey, 1).qps_limit = None
        self.db.commit()
        self.reply = lambda _request: httpx.Response(
            200, headers={"content-type": "text/event-stream"},
            content=b'data: {"choices":[],"usage":{"prompt_tokens":2,'
                    b'"completion_tokens":5,"total_tokens":7}}\n\n'
                    b'data: [DONE]\n\n',
        )
        response = self.client.post(
            "/v1/chat/completions", json={**self.body, "stream": True}, headers=self.headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.db.query(UsageRecord).one().estimated_cost, Decimal("0.05"))

    def test_tier_validation_requires_ordered_unbounded_last_tier(self):
        base = dict(provider_id=1, protocol_id=1, access_model_code="tiered",
                    provider_model_name="tiered", model_type="llm", tiered_pricing=True)
        with self.assertRaises(ValueError):
            AccessModelCreate(**base)
        with self.assertRaises(ValueError):
            AccessModelCreate(**{**base,
                "input_price_tiers": [
                    {"up_to_tokens": 10, "price": "1.00"},
                    {"up_to_tokens": 10, "price": "2.00"},
                ],
                "output_price_tiers": [{"up_to_tokens": None, "price": "3.00"}],
            })
        priced = AccessModelCreate(**{**base,
            "input_price_tiers": [{"up_to_tokens": None, "price": "2.005"}],
            "output_price_tiers": [{"up_to_tokens": None, "price": "3.00"}],
        })
        self.assertEqual(priced.input_price_tiers[0].price, Decimal("2.01"))

    def test_access_model_tiers_persist_and_reject_incomplete_update(self):
        admin = self.db.get(User, 1)
        admin.is_platform_admin = 1
        self.db.commit()
        app.dependency_overrides[actor] = lambda: admin
        url = "/api/admin/v1/access-models/1"
        payload = {
            "tiered_pricing": True,
            "input_price_tiers": [
                {"up_to_tokens": 1000, "price": "1.005"},
                {"up_to_tokens": None, "price": "2.00"},
            ],
            "output_price_tiers": [{"up_to_tokens": None, "price": "3.00"}],
        }
        response = self.client.patch(url, json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        detail = self.client.get(url)
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["data"]["input_price_tiers"][0]["price"], "1.01")
        self.assertEqual(self.db.get(ProviderModel, 1).input_price_tiers[0]["price"], "1.01")
        invalid = self.client.patch(url, json={"input_price_tiers": [
            {"up_to_tokens": 10, "price": "1.00"},
        ]})
        self.assertEqual(invalid.status_code, 422)
        created = self.client.post("/api/admin/v1/access-models", json={
            "provider_id": 1, "protocol_id": 1, "access_model_code": "tiered-new",
            "provider_model_name": "tiered-new", "model_type": "llm",
            "tiered_pricing": True,
            "input_price_tiers": [{"up_to_tokens": None, "price": "1.23"}],
            "output_price_tiers": [{"up_to_tokens": None, "price": "4.56"}],
        })
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(
            self.db.get(ProviderModel, created.json()["data"]["id"]).input_price_tiers[0]["price"],
            "1.23",
        )

    def test_failed_upstream_releases_amount_reservation(self):
        model = self.db.get(ProviderModel, 1)
        model.input_price = Decimal("1.00")
        model.output_price = Decimal("1.00")
        self.db.get(Project, 1).amount_budget = Decimal("0.02")
        self.db.get(ApiKey, 1).qps_limit = None
        self.db.commit()
        self.reply = lambda _request: httpx.Response(500, json={"error": "unavailable"})
        failed = self.client.post("/v1/chat/completions", json=self.body, headers=self.headers)
        self.assertEqual(failed.status_code, 502)
        self.reply = None
        succeeded = self.client.post("/v1/chat/completions", json=self.body, headers=self.headers)
        self.assertEqual(succeeded.status_code, 200, succeeded.text)
        self.assertEqual(self.db.query(UsageRecord).count(), 1)

    def configure_retry(self, strategy="round_robin", enabled=True):
        self.db.add(ProviderModel(
            id=3, provider_id=1, protocol_id=1, access_model_code="backup-chat",
            provider_model_name="backup-upstream", model_type="llm",
        ))
        aggregate = self.db.get(AggregatedModel, 1)
        aggregate.default_routing_strategy = strategy
        aggregate.routing_model_ids = [1, 3]
        aggregate.retry_on_failure = enabled
        self.db.get(ApiKey, 1).qps_limit = None
        self.db.commit()

    def test_retry_round_robin_skips_failed_node_and_settles_once(self):
        self.configure_retry()
        def upstream(request):
            if json.loads(request.content)["model"] == "upstream-chat":
                return httpx.Response(503, json={"error": "unavailable"})
            return httpx.Response(200, json={
                "choices": [{"message": {"content": "backup"}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
            })
        self.reply = upstream
        with patch("app.api.gateway.router.rounds", iter([0, 0, 0, 0, 0, 0])):
            response = self.client.post("/v1/chat/completions", json=self.body,
                                        headers=self.headers)
            second = self.client.post("/v1/chat/completions", json=self.body,
                                      headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual([json.loads(call.content)["model"] for call in self.calls],
                         ["upstream-chat", "backup-upstream", "backup-upstream"])
        self.assertEqual(self.db.query(UsageRecord).count(), 2)
        logs = self.db.query(RequestLog).order_by(RequestLog.id).all()
        self.assertEqual([(log.provider_model_id, log.http_status) for log in logs],
                         [(1, 502), (3, 200), (3, 200)])
        self.assertEqual(logs[0].provider_status, "503")
        self.assertNotEqual(logs[0].request_id, logs[1].request_id)
        self.assertIn(logs[1].request_id, logs[0].error_message)
        self.assertEqual(asyncio.run(self.fake.ttl(cooldown_key(1))), 300)
        asyncio.run(self.fake.delete(cooldown_key(1)))
        with patch("app.api.gateway.router.rounds", iter([0, 0])):
            restored = self.client.post("/v1/chat/completions", json=self.body,
                                        headers=self.headers)
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(json.loads(self.calls[-2].content)["model"], "upstream-chat")

    def test_retry_least_latency_and_exhausted_candidates(self):
        self.configure_retry("least_latency")
        self.reply = lambda _request: httpx.Response(503, json={"error": "unavailable"})
        failed = self.client.post("/v1/chat/completions", json=self.body,
                                  headers=self.headers)
        self.assertEqual(failed.status_code, 502, failed.text)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.db.query(RequestLog).count(), 2)
        self.assertEqual(self.db.query(UsageRecord).count(), 0)
        self.assertEqual(asyncio.run(self.fake.ttl(cooldown_key(1))), 300)
        self.assertEqual(asyncio.run(self.fake.ttl(cooldown_key(3))), 300)
        still_cooling = self.client.post("/v1/chat/completions", json=self.body,
                                         headers=self.headers)
        self.assertEqual(still_cooling.status_code, 503)
        self.assertEqual(len(self.calls), 2)

    def test_retry_disabled_does_not_switch(self):
        self.configure_retry(enabled=False)
        self.reply = lambda _request: httpx.Response(503, json={"error": "unavailable"})
        with patch("app.api.gateway.router.rounds", iter([0, 0])):
            failed = self.client.post("/v1/chat/completions", json=self.body,
                                      headers=self.headers)
        self.assertEqual(failed.status_code, 502)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(asyncio.run(self.fake.exists(cooldown_key(1))), 0)

    def test_retry_stream_before_response_begins(self):
        self.configure_retry("least_latency")
        def upstream(request):
            if json.loads(request.content)["model"] == "upstream-chat":
                return httpx.Response(503)
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"},
                content=b'data: {"choices":[{"delta":{"content":"backup"}}]}\n\n'
                        b'data: {"choices":[],"usage":{"prompt_tokens":2,'
                        b'"completion_tokens":3,"total_tokens":5}}\n\n'
                        b'data: [DONE]\n\n',
            )
        self.reply = upstream
        response = self.client.post("/v1/chat/completions", json={
            **self.body, "stream": True,
        }, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("backup", response.text)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.db.query(UsageRecord).one().provider_model_id, 3)
        self.assertEqual([(log.provider_model_id, log.http_status)
                          for log in self.db.query(RequestLog).order_by(RequestLog.id)],
                         [(1, 502), (3, 200)])
        self.assertEqual(asyncio.run(self.fake.ttl(cooldown_key(1))), 300)

    def test_aggregate_node_detail_status_and_recent_performance(self):
        self.configure_retry("least_latency")
        self.db.get(User, 1).is_platform_admin = 1
        self.db.get(ProviderModel, 3).status = 0
        self.db.add(ProviderModel(
            id=4, provider_id=1, protocol_id=1, access_model_code="fallback-chat",
            provider_model_name="fallback-upstream", model_type="llm",
        ))
        self.db.get(AggregatedModel, 1).fallback_model_id = 4
        self.db.add(AggregatedModel(
            id=2, aggregate_model_code="another", public_model_name="another",
            model_type="llm", routing_model_ids=[1], default_routing_strategy="single",
        ))
        now = datetime.now(UTC).replace(tzinfo=None)
        def log(log_id, aggregate_id, status, ttft, latency, created_at, output=None):
            entry = RequestLog(
                id=log_id, request_id=f"req_detail_{log_id}",
                aggregate_model_id=aggregate_id, provider_model_id=1,
                public_model_name="public-chat", model_type="llm",
                endpoint="/v1/chat/completions", requester_ip="127.0.0.1",
                http_status=status, ttft_ms=ttft, latency_ms=latency,
                created_at=created_at,
            )
            self.db.add(entry)
            if output is not None:
                self.db.add(UsageRecord(
                    request_log_id=log_id, model_type="llm", output_tokens=output,
                ))
        log(1, 1, 200, 100, 1100, now, 10)
        log(2, 1, 200, 200, 700, now, 5)
        log(3, 1, 502, 900, 1000, now, 30)
        log(4, 1, 200, 500, 600, now - timedelta(days=2), 10)
        log(5, 2, 200, 500, 600, now, 10)
        self.db.commit()
        asyncio.run(self.fake.set(cooldown_key(1), "1", ex=300))
        app.dependency_overrides[actor] = lambda: self.db.get(User, 1)
        url = "/api/admin/v1/aggregate-models/1/nodes"
        with patch("app.modules.model.router.limiter", side_effect=lambda: Limiter(self.fake)):
            response = self.client.get(url)
            self.assertEqual(self.client.get("/api/admin/v1/aggregate-models/999/nodes").status_code,
                             404)
        self.assertEqual(response.status_code, 200, response.text)
        nodes = response.json()["data"]["nodes"]
        self.assertEqual(response.json()["data"]["window_hours"], 24)
        self.assertEqual([(item["model_id"], item["status"], item["role"]) for item in nodes], [
            (1, "cooldown", "candidate"), (3, "disabled", "candidate"),
            (4, "available", "fallback"),
        ])
        self.assertGreater(nodes[0]["cooldown_seconds"], 0)
        self.assertEqual((nodes[0]["avg_ttft_ms"], nodes[0]["avg_tps"]), (150, 10))
        self.assertEqual((nodes[0]["ttft_samples"], nodes[0]["tps_samples"]), (2, 2))
        self.assertIsNone(nodes[1]["avg_ttft_ms"])
        self.assertIsNone(nodes[2]["avg_tps"])

    def test_aggregate_probe_selected_nodes_and_permissions(self):
        self.configure_retry()
        url = "/api/admin/v1/aggregate-models/1/nodes/probe"
        payload = {"model_ids": [1, 3], "mode": "network"}
        app.dependency_overrides[actor] = lambda: self.db.get(User, 1)
        self.assertEqual(self.client.post(url, json=payload).status_code, 403)
        self.db.get(User, 1).is_platform_admin = 1
        self.db.commit()
        self.assertEqual(self.client.post(url, json={
            "model_ids": [2], "mode": "actual",
        }).status_code, 422)
        self.assertEqual(self.client.post(url, json={
            "model_ids": [1, 1], "mode": "network",
        }).status_code, 422)
        writer = MagicMock()
        writer.wait_closed = AsyncMock()
        with patch("app.modules.model.router.asyncio.open_connection",
                   new_callable=AsyncMock, return_value=(None, writer)) as connect:
            response = self.client.post(url, json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([item["result"] for item in response.json()["data"]["results"]],
                         ["ok", "ok"])
        self.assertEqual(connect.await_count, 2)
        self.assertFalse(self.calls)
        self.assertEqual(self.db.query(RequestLog).count(), 0)

    def test_aggregate_actual_probe_does_not_modify_cooldown_or_usage(self):
        self.configure_retry()
        self.db.get(User, 1).is_platform_admin = 1
        self.db.commit()
        app.dependency_overrides[actor] = lambda: self.db.get(User, 1)
        asyncio.run(self.fake.set(cooldown_key(1), "1", ex=300))
        url = "/api/admin/v1/aggregate-models/1/nodes/probe"
        self.reply = lambda _request: httpx.Response(
            200, json={"choices": [{"message": {"content": "pong"}}]},
        )
        succeeded = self.client.post(url, json={"model_ids": [1], "mode": "actual"})
        self.assertEqual(succeeded.status_code, 200, succeeded.text)
        self.assertEqual(succeeded.json()["data"]["results"][0]["result"], "ok")
        self.assertEqual(json.loads(self.calls[0].content)["max_tokens"], 1)
        self.reply = lambda _request: httpx.Response(503, json={"error": "down"})
        failed = self.client.post(url, json={"model_ids": [3], "mode": "actual"})
        self.assertEqual(failed.json()["data"]["results"][0]["result"], "failed")
        self.assertEqual(failed.json()["data"]["results"][0]["http_status"], 503)
        self.assertEqual(asyncio.run(self.fake.exists(cooldown_key(3))), 0)
        self.assertGreater(asyncio.run(self.fake.ttl(cooldown_key(1))), 0)
        self.assertEqual(self.db.query(RequestLog).count(), 0)
        self.assertEqual(self.db.query(UsageRecord).count(), 0)

    def test_pricing_requires_both_sides(self):
        payload = dict(provider_id=1, protocol_id=1, access_model_code="new",
                       provider_model_name="new", model_type="llm", input_price="1.00")
        with self.assertRaises(ValueError):
            AccessModelCreate(**payload)
        priced = AccessModelCreate(**{**payload, "output_price": "2.005"})
        self.assertEqual(priced.output_price, Decimal("2.01"))

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

    def test_reasoning_usage_and_stream_performance_logged(self):
        self.db.get(ApiKey, 1).qps_limit = None
        self.db.commit()
        self.reply = lambda _request: httpx.Response(200, json={
            "choices": [{"message": {"content": "answer"}}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 6, "total_tokens": 10,
                      "completion_tokens_details": {"reasoning_tokens": 2}},
        })
        response = self.client.post("/v1/chat/completions", json=self.body,
                                    headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        record = self.db.query(UsageRecord).one()
        self.assertEqual((record.input_tokens, record.output_tokens,
                          record.reasoning_tokens, record.non_reasoning_tokens), (4, 6, 2, 4))
        self.reply = lambda _request: httpx.Response(
            200, headers={"content-type": "text/event-stream"},
            content=b'data: {"choices":[{"delta":{"reasoning_content":"think"}}]}\n\n'
                    b'data: {"choices":[{"delta":{"content":"answer"}}]}\n\n'
                    b'data: {"choices":[],"usage":{"prompt_tokens":4,'
                    b'"completion_tokens":6,"total_tokens":10,'
                    b'"completion_tokens_details":{"reasoning_tokens":2}}}\n\n'
                    b'data: [DONE]\n\n',
        )
        streamed = self.client.post("/v1/chat/completions", json={
            **self.body, "stream": True,
        }, headers=self.headers)
        self.assertEqual(streamed.status_code, 200, streamed.text)
        log = self.db.query(RequestLog).order_by(RequestLog.id.desc()).first()
        self.assertIsNotNone(log.ttft_ms)
        self.assertIsNotNone(log.tpot_ms)
        self.assertEqual(self.db.query(UsageRecord).order_by(UsageRecord.id.desc())
                         .first().non_reasoning_tokens, 4)

    def test_gemini_thought_tokens_count_as_output(self):
        payload = {"usageMetadata": {
            "promptTokenCount": 3, "candidatesTokenCount": 4,
            "thoughtsTokenCount": 2, "totalTokenCount": 9,
        }}
        self.assertEqual(usage_counts(payload, "gemini"), (9, 3, 6))
        self.assertEqual(reasoning_count(payload, "gemini"), 2)

    def test_archived_request_image_previews_require_admin(self):
        self.db.get(User, 1).is_platform_admin = True
        self.db.commit()
        app.dependency_overrides[actor] = lambda: self.db.get(User, 1)
        self.assertEqual(self.client.post("/v1/chat/completions", json=self.body,
                                          headers=self.headers).status_code, 200)
        request_id = self.db.query(RequestLog).one().request_id
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
        payload = json.dumps({"messages": [{"content": [
            {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
            {"type": "image_url", "image_url": {
                "url": "data:image/png;base64," + base64.b64encode(png).decode(),
            }},
        ]}]}).encode()
        settings = get_settings().model_copy(update={
            "log_archive_enabled": True, "log_archive_bucket": "call-logs",
        })
        client = MagicMock()
        def object_at(**kwargs):
            contents = payload if kwargs["Key"].endswith("request.bin") else json.dumps({
                "files": ["request.bin"], "capture_complete": True,
            }).encode()
            return {"Body": io.BytesIO(contents)}
        client.get_object.side_effect = object_at
        client.generate_presigned_url.return_value = "http://storage/private"
        with patch("app.modules.audit.router.get_settings", return_value=settings), \
             patch("app.modules.audit.router.s3_client", return_value=client):
            detail = self.client.get(f"/api/admin/v1/logs/requests/{request_id}").json()["data"]
            self.assertEqual(len(detail["images"]), 2)
            self.assertNotIn("base64,", json.dumps(detail["images"]))
            preview = self.client.get(f"/api/admin/v1/logs/requests/{request_id}/images/1")
            self.assertEqual(preview.content, png)
            self.assertEqual(preview.headers["content-type"], "image/png")
            self.assertEqual(
                self.client.get(f"/api/admin/v1/logs/requests/{request_id}/images/0").status_code,
                404,
            )
        self.assertEqual(image_entries(json.dumps({"image": base64.b64encode(png).decode()})
                                       .encode())[0][0], "base64")

    def test_raw_preview_requires_admin_limits_size_and_closes_storage_stream(self):
        self.assertEqual(self.client.post("/v1/chat/completions", json=self.body,
                                          headers=self.headers).status_code, 200)
        request_id = self.db.query(RequestLog).one().request_id
        url = f"/api/admin/v1/logs/requests/{request_id}/raw/upstream_response.bin"
        self.assertEqual(self.client.get(url).status_code, 401)
        app.dependency_overrides[actor] = lambda: self.db.get(User, 1)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.db.get(User, 1).is_platform_admin = True
        self.db.commit()
        settings = get_settings().model_copy(update={
            "log_archive_enabled": True, "log_archive_bucket": "call-logs",
        })
        client = MagicMock()
        payload = '{"content":"你好","reasoning_content":"test"}'.encode()
        streams = []

        def object_at(**_kwargs):
            stream = io.BytesIO(payload)
            streams.append(stream)
            return {"Body": stream, "ContentLength": len(payload)}

        client.get_object.side_effect = object_at
        with patch("app.modules.audit.router.get_settings", return_value=settings), \
             patch("app.modules.audit.router.s3_client", return_value=client):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["data"]["text"], payload.decode())
            self.assertFalse(response.json()["data"]["truncated"])
            self.assertTrue(streams[-1].closed)
            with patch("app.modules.audit.router.MAX_RAW_PREVIEW_BYTES", 8):
                response = self.client.get(url)
                self.assertTrue(response.json()["data"]["truncated"])
                self.assertEqual(len(response.json()["data"]["text"].encode()), 8)
            self.assertEqual(self.client.get(url.replace("upstream_response.bin", "secret.bin"))
                             .status_code, 422)
            self.assertEqual(self.client.get(url.replace(request_id, "missing"))
                             .status_code, 404)

    def test_raw_archive_preserves_headers_images_and_both_streams(self):
        key = self.db.get(ApiKey, 1)
        key.qps_limit = None
        self.db.commit()
        self.reply = lambda _request: httpx.Response(
            200, headers={"content-type": "text/event-stream"},
            content=b'data: {"choices":[{"delta":{"content":"raw"}}]}\r\n\r\n'
                    b'data: {"choices":[],"usage":{"prompt_tokens":1,'
                    b'"completion_tokens":2,"total_tokens":3}}\n\n'
                    b'data: [DONE]\n\n',
        )
        with tempfile.TemporaryDirectory() as folder:
            settings = get_settings().model_copy(update={
                "log_archive_enabled": True, "log_archive_spool_dir": folder,
            })
            with patch("app.modules.gateway.archive.get_settings", return_value=settings):
                body = json.dumps({
                    **self.body, "stream": True,
                    "messages": [{"role": "user", "content": [
                        {"type": "image_url", "image_url": {
                            "url": "data:image/png;base64,AQIDBA==",
                        }},
                    ]}],
                }).encode()
                response = self.client.post(
                    "/v1/chat/completions", content=body,
                    headers={**self.headers, "content-type": "application/json",
                             "x-custom-original": "preserve"},
                )
                self.assertEqual(response.status_code, 200)
                request_id = response.headers["x-gateway-request-id"]
                self.assertEqual(self.db.query(RequestLog).one().request_id, request_id)
                manifest_file = next(Path(folder).rglob("manifest.pending"))
                directory = manifest_file.parent
                manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
                self.assertEqual((directory / "request.bin").read_bytes(), body)
                self.assertIn(["x-custom-original", "preserve"], manifest["request_headers"])
                self.assertIn(b"base64,AQIDBA==", (directory / "upstream_request.bin").read_bytes())
                self.assertIn(b"\r\n\r\n", (directory / "upstream_response.bin").read_bytes())
                self.assertIn(b"data: [DONE]\n\n", (directory / "response.bin").read_bytes())
                self.assertTrue(manifest["capture_complete"])
                settings.log_archive_bucket = "test"
                settings.log_archive_prefix = "calls"
                client = MagicMock()
                with patch("boto3.client", return_value=client), \
                     patch("app.modules.gateway.archive.SessionLocal",
                           side_effect=lambda: Session(self.engine)):
                    _upload(directory, Path(folder))
                self.assertFalse(directory.exists())
                self.assertEqual(client.upload_file.call_count, 4)
                self.assertEqual(client.put_object.call_args.kwargs["Key"],
                                 f"calls/{manifest_file.parent.relative_to(folder).as_posix()}/"
                                 "manifest.json")

    def test_call_log_list_and_detail_require_platform_admin(self):
        self.assertEqual(self.client.post("/v1/chat/completions", json=self.body,
                                          headers=self.headers).status_code, 200)
        request_id = self.db.query(RequestLog).one().request_id
        self.assertEqual(self.client.get("/api/admin/v1/logs/requests").status_code, 401)
        app.dependency_overrides[actor] = lambda: self.db.get(User, 1)
        self.assertEqual(self.client.get("/api/admin/v1/logs/requests").status_code, 403)
        self.db.get(User, 1).is_platform_admin = True
        self.db.commit()
        listing = self.client.get("/api/admin/v1/logs/requests").json()["data"]
        self.assertEqual(listing["total"], 1)
        self.assertEqual(listing["items"][0]["request_id"], request_id)
        raw_key = self.headers["Authorization"].split(" ", 1)[1]
        masked = f"{raw_key[:8]}****{raw_key[-4:]}"
        self.assertEqual(listing["items"][0]["api_key_masked"], masked)
        self.assertTrue(listing["items"][0]["api_key_snapshot"])
        self.assertNotIn(raw_key, json.dumps(listing))
        log = self.db.query(RequestLog).one()
        self.db.get(ApiKey, 1).key_prefix = "rotated"
        self.db.commit()
        unchanged = self.client.get("/api/admin/v1/logs/requests").json()["data"]["items"][0]
        self.assertEqual(unchanged["api_key_masked"], masked)
        log.api_key_masked = None
        self.db.commit()
        historical = self.client.get("/api/admin/v1/logs/requests").json()["data"]["items"][0]
        self.assertEqual(historical["api_key_masked"], "rotated****")
        self.assertFalse(historical["api_key_snapshot"])
        log.api_key_masked = masked
        log.latency_ms = 2000
        self.db.commit()
        measured = self.client.get("/api/admin/v1/logs/requests").json()["data"]["items"][0]
        self.assertEqual(measured["tps"], 1.5)
        log.latency_ms = 0
        self.db.commit()
        measured = self.client.get("/api/admin/v1/logs/requests").json()["data"]["items"][0]
        self.assertIsNone(measured["tps"])
        filtered = self.client.get("/api/admin/v1/logs/requests", params={
            "filters": json.dumps({"mode": "and", "conditions": [
                {"field": "total_tokens", "operator": "eq", "value": "5"},
                {"field": "request_id", "operator": "eq", "value": request_id},
            ]}),
        })
        self.assertEqual(filtered.status_code, 200, filtered.text)
        self.assertEqual(filtered.json()["data"]["total"], 1)
        detail = self.client.get(f"/api/admin/v1/logs/requests/{request_id}").json()["data"]
        self.assertEqual(detail["total_tokens"], 5)
        self.assertIsNone(detail["archive"])
        settings = get_settings().model_copy(update={
            "log_archive_enabled": True, "log_archive_bucket": "call-logs",
        })
        client = MagicMock()
        client.get_object.return_value = {
            "Body": io.BytesIO(json.dumps({
                "files": ["request.bin"], "capture_complete": True,
            }).encode()),
        }
        client.generate_presigned_url.return_value = "http://storage/private"
        with patch("app.modules.audit.router.get_settings", return_value=settings), \
             patch("app.modules.audit.router.s3_client", return_value=client):
            archive = self.client.get(f"/api/admin/v1/logs/requests/{request_id}").json()
        self.assertEqual(archive["data"]["archive"]["downloads"]["request.bin"],
                         "http://storage/private")

    def test_rejected_request_is_archived_and_indexed_in_background(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = get_settings().model_copy(update={
                "log_archive_enabled": True, "log_archive_spool_dir": folder,
                "log_archive_bucket": "test", "log_archive_prefix": "calls",
            })
            with patch("app.modules.gateway.archive.get_settings", return_value=settings):
                response = self.client.post("/v1/chat/completions", json=self.body,
                                            headers={"Authorization": "Bearer invalid"})
                self.assertEqual(response.status_code, 401)
                pending = next(Path(folder).rglob("manifest.pending"))
                directory = pending.parent
                manifest = json.loads(pending.read_text(encoding="utf-8"))
                self.assertIn(["authorization", "Bearer invalid"],
                              [[key.lower(), value] for key, value in manifest["request_headers"]])
                client = MagicMock()
                with patch("boto3.client", return_value=client), \
                     patch("app.modules.gateway.archive.SessionLocal",
                           side_effect=lambda: Session(self.engine)):
                    _upload(directory, Path(folder))
            self.db.expire_all()
            log = self.db.query(RequestLog).one()
            self.assertEqual(log.request_id, response.headers["x-gateway-request-id"])
            self.assertEqual(log.http_status, 401)

    def test_global_image_policy_and_remote_image_archival(self):
        self.assertEqual(self.client.get("/api/admin/v1/settings/log-archive").status_code, 401)
        app.dependency_overrides[actor] = lambda: self.db.get(User, 1)
        self.assertEqual(self.client.get("/api/admin/v1/settings/log-archive").status_code, 403)
        self.db.get(User, 1).is_platform_admin = True
        self.db.commit()
        path = "/api/admin/v1/settings/log-archive"
        self.assertEqual(self.client.get(path).json()["data"]["image_mode"], "content_only")
        self.assertEqual(self.client.put(path, json={"image_mode": "all"}).status_code, 422)
        self.assertEqual(self.client.put(
            path, json={"image_mode": "mirror_images"},
        ).json()["data"]["image_mode"], "mirror_images")
        self.assertEqual(self.client.get(path).json()["data"]["image_mode"], "mirror_images")

        with tempfile.TemporaryDirectory() as folder:
            settings = get_settings().model_copy(update={
                "log_archive_spool_dir": folder, "log_archive_bucket": "test",
                "log_archive_prefix": "calls",
            })
            archive = CallArchive({
                "method": "POST", "path": "/v1/images/generations",
                "headers": [], "client": ("127.0.0.1", 4000),
            }, Path(folder))
            archive.write("upstream_response.bin", json.dumps({
                "data": [{"url": "https://images.example.com/result.png"}],
            }).encode())
            archive.manifest["db_recorded"] = True
            archive.finish()
            client = MagicMock()
            image = MagicMock()
            image.iter_bytes.return_value = [b"\x89PNG", b"content"]
            http = MagicMock()
            http.stream.return_value.__enter__.return_value = image
            with patch("app.modules.gateway.archive.get_settings", return_value=settings), \
                 patch("app.modules.gateway.archive.s3_client", return_value=client), \
                 patch("app.modules.gateway.archive.SessionLocal",
                       side_effect=lambda: Session(self.engine)), \
                 patch("app.modules.gateway.archive.httpx.Client") as http_type:
                http_type.return_value.__enter__.return_value = http
                _upload(archive.directory, Path(folder))
            self.assertEqual(client.upload_file.call_count, 2)
            manifest = json.loads(client.put_object.call_args.kwargs["Body"])
            self.assertEqual(manifest["image_mode"], "mirror_images")
            self.assertTrue(manifest["external_images"][0]["saved"])
            self.assertFalse(archive.directory.exists())

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
