import json
import unittest
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token
from app.db.base import Base
from app.db.models import (
    ApiKey,
    Organization,
    Project,
    Provider,
    ProviderModel,
    RequestLog,
    UsageRecord,
    User,
)
from app.db.session import get_db
from app.main import app


@compiles(BigInteger, "sqlite")
def bigint_sqlite(_type, _compiler, **_kwargs):
    return "INTEGER"


@compiles(JSONB, "sqlite")
def jsonb_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


class AnalyticsTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine, tables=[
            User.__table__, Organization.__table__, Project.__table__, ApiKey.__table__,
            Provider.__table__, ProviderModel.__table__, RequestLog.__table__,
            UsageRecord.__table__,
        ])
        self.db = Session(self.engine)
        self.db.add_all([
            User(id=1, username="admin", email="admin@test.local", password_hash="hash",
                 is_platform_admin=1),
            User(id=2, username="user", email="user@test.local", password_hash="hash"),
            Provider(id=1, name="Alpha", code="alpha", provider_type="openai", base_url="x"),
            ProviderModel(id=1, provider_id=1, access_model_code="model-a",
                          provider_model_name="upstream-a", model_type="llm"),
        ])
        self.db.commit()
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.admin = {"Authorization": f"Bearer {create_access_token('1')}"}
        self.member = {"Authorization": f"Bearer {create_access_token('2')}"}
        self.path = "/api/admin/v1/analytics"
        self.dates = {"start_date": "2026-09-27", "end_date": "2026-09-28"}

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()

    def log(self, identifier, day, status, *, tokens=None, cost=None, latency=None,
            ttft=None, tpot=None, provider=1, model=1, currency="CNY"):
        stamp = datetime(2026, 9, day, 12)
        self.db.add(RequestLog(
            id=identifier, request_id=f"req-{identifier}", provider_id=provider,
            provider_model_id=model, public_model_name="chat",
            model_type="llm", endpoint="/v1/chat/completions", requester_ip="127.0.0.1",
            http_status=status, latency_ms=latency, ttft_ms=ttft, tpot_ms=tpot,
            error_code="timeout" if status == 504 else None, created_at=stamp,
        ))
        if tokens is not None:
            self.db.add(UsageRecord(
                id=identifier, request_log_id=identifier, provider_id=provider,
                provider_model_id=model, model_type="llm", total_tokens=tokens,
                input_tokens=tokens // 2, output_tokens=tokens - tokens // 2,
                estimated_cost=Decimal(cost) if cost is not None else None,
                currency=currency, created_at=stamp + timedelta(days=1),
            ))
        self.db.commit()

    def get(self, kind, **params):
        return self.client.get(f"{self.path}/{kind}", headers=self.admin,
                               params={**self.dates, **params})

    def test_access_validation_and_empty_calendar(self):
        for kind in ("usage", "cost", "performance", "currencies"):
            self.assertEqual(self.client.get(f"{self.path}/{kind}").status_code, 401)
            self.assertEqual(
                self.client.get(f"{self.path}/{kind}", headers=self.member).status_code, 403,
            )
        self.assertEqual(self.get("usage", start_date="2026-09-29").status_code, 422)
        self.assertEqual(self.get("usage", start_date="2026-01-01").status_code, 422)
        self.assertEqual(self.get("usage", scope="project").status_code, 422)
        self.assertEqual(self.get("usage", scope="project", value="oops").status_code, 422)
        empty = self.get("usage").json()["data"]
        self.assertEqual(empty["summary"]["requests"], 0)
        self.assertEqual(len(empty["daily"]), 2)
        self.assertEqual(empty["ranking"], [])
        self.assertEqual(self.get("performance").json()["data"]["summary"]["p95_latency_ms"],
                         None)

    def test_usage_uses_request_timestamp_and_includes_requests_without_usage(self):
        self.log(1, 27, 200, tokens=10, cost="1.25", latency=100)
        self.log(2, 28, 504, latency=500)
        self.log(3, 26, 200, tokens=99, cost="9.00")
        result = self.get("usage").json()["data"]
        self.assertEqual(result["summary"]["requests"], 2)
        self.assertEqual(result["summary"]["successes"], 1)
        self.assertEqual(result["summary"]["total_tokens"], 10)
        self.assertEqual([day["requests"] for day in result["daily"]], [1, 1])
        self.assertEqual(result["ranking"][0]["label"], "chat")
        filtered = self.get("usage", scope="access_model", value="1",
                            dimension="access_model").json()["data"]
        self.assertEqual(filtered["ranking"][0]["label"], "model-a")
        self.assertEqual(self.get("usage", scope="provider", value="2").json()
                         ["data"]["summary"]["requests"], 0)

    def test_cost_separates_unpriced_and_currency_and_preserves_zero(self):
        self.log(1, 27, 200, tokens=10, cost="0.00")
        self.log(2, 28, 200, tokens=20, cost="2.50")
        self.log(3, 28, 504, latency=300)
        self.log(4, 28, 200, tokens=30, cost="3.00", currency="USD")
        result = self.get("cost").json()["data"]
        self.assertEqual(result["summary"]["requests"], 4)
        self.assertEqual(result["summary"]["priced_requests"], 2)
        self.assertEqual(result["summary"]["unpriced_requests"], 2)
        self.assertEqual(Decimal(result["summary"]["estimated_cost"]), Decimal("2.50"))
        self.assertEqual(Decimal(result["summary"]["average_cost"]), Decimal("1.25"))
        self.assertEqual(result["ranking"][0]["label"], "Alpha")
        self.assertEqual(Decimal(self.get("cost", currency="USD").json()
                         ["data"]["summary"]["estimated_cost"]), Decimal("3.00"))
        self.assertEqual(self.client.get(f"{self.path}/currencies", headers=self.admin)
                         .json()["data"], ["CNY", "USD"])

    def test_performance_percentiles_exclude_null_and_error_distribution(self):
        self.log(1, 27, 200, tokens=10, latency=100, ttft=20, tpot=8)
        self.log(2, 28, 504, latency=300)
        self.log(3, 28, 200, latency=200, ttft=40, tpot=12)
        self.log(4, 28, 200)
        summary = self.get("performance").json()["data"]
        self.assertEqual(summary["summary"]["requests"], 4)
        self.assertEqual(summary["summary"]["latency_samples"], 3)
        self.assertEqual(summary["summary"]["avg_latency_ms"], 200)
        self.assertEqual(summary["summary"]["p95_latency_ms"], 290)
        self.assertEqual(summary["summary"]["p99_latency_ms"], 298)
        self.assertEqual(summary["summary"]["avg_ttft_ms"], 30)
        self.assertEqual(summary["summary"]["ttft_samples"], 2)
        self.assertEqual(summary["summary"]["avg_tpot_ms"], 10)
        self.assertEqual(summary["summary"]["speed_samples"], 1)
        self.assertEqual(summary["summary"]["avg_tokens_per_second"], 62.5)
        self.assertEqual(summary["daily"][1]["p95_latency_ms"], 295)
        self.assertEqual(summary["daily"][0]["p99_latency_ms"], 100)
        self.assertEqual(summary["errors"][0]["code"], "timeout")
        self.assertEqual(summary["ranking"][0]["label"], "model-a")

    def test_default_currency_is_available_with_only_historical_foreign_costs(self):
        self.log(1, 27, 200, tokens=10, cost="1.00", currency="USD")
        result = self.client.get(f"{self.path}/currencies", headers=self.admin).json()["data"]
        self.assertEqual(result, ["CNY", "USD"])

    def test_logs_drilldown_keeps_dates_and_unassigned_dimension(self):
        self.log(1, 27, 200, tokens=10, cost="0.00")
        self.log(2, 28, 504)
        self.log(3, 26, 200)
        filters = json.dumps({"mode": "and", "conditions": [
            {"field": "created_at", "operator": "gte", "value": "2026-09-27"},
            {"field": "created_at", "operator": "lt", "value": "2026-09-29"},
            {"field": "project_unassigned", "operator": "eq", "value": "1"},
            {"field": "provider", "operator": "eq", "value": "1"},
        ]})
        result = self.client.get("/api/admin/v1/logs/requests", headers=self.admin,
                                 params={"filters": filters}).json()["data"]
        self.assertEqual(result["total"], 2)
        self.assertEqual({item["request_id"] for item in result["items"]}, {"req-1", "req-2"})


if __name__ == "__main__":
    unittest.main()
