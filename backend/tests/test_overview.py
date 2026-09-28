import unittest
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token
from app.db.base import Base
from app.db.models import RequestLog, UsageRecord, User
from app.db.session import get_db
from app.main import app
from app.modules.overview.service import get_overview_activity


@compiles(BigInteger, "sqlite")
def bigint_sqlite(_type, _compiler, **_kwargs):
    return "INTEGER"


@compiles(JSONB, "sqlite")
def jsonb_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


class OverviewTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(
            self.engine, tables=[User.__table__, RequestLog.__table__, UsageRecord.__table__],
        )
        self.db = Session(self.engine)
        self.db.add_all([
            User(id=1, username="admin", email="admin@example.com", password_hash="hash",
                 is_platform_admin=1),
            User(id=2, username="member", email="member@example.com", password_hash="hash"),
        ])
        self.db.commit()
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.admin = {"Authorization": f"Bearer {create_access_token('1')}"}
        self.member = {"Authorization": f"Bearer {create_access_token('2')}"}

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()

    def add_log(self, identifier, created, status, model, tokens=None):
        self.db.add(RequestLog(
            id=identifier, request_id=f"request-{identifier}", public_model_name=model,
            model_type="llm", endpoint="/v1/chat/completions", requester_ip="127.0.0.1",
            http_status=status, created_at=created,
        ))
        if tokens is not None:
            self.db.add(UsageRecord(
                id=identifier, request_log_id=identifier, model_type="llm",
                total_tokens=tokens, created_at=created + timedelta(days=1),
            ))
        self.db.commit()

    def test_empty_days_and_access(self):
        path = "/api/admin/v1/overview/activity"
        self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.get(path, headers=self.member).status_code, 403)
        summary = "/api/admin/v1/overview/summary"
        self.assertEqual(self.client.get(summary).status_code, 401)
        self.assertEqual(self.client.get(summary, headers=self.member).status_code, 403)
        self.assertEqual(
            self.client.get(path, headers=self.admin, params={"days": 6}).status_code, 422,
        )
        data = self.client.get(path, headers=self.admin).json()["data"]
        self.assertEqual(len(data["daily"]), 7)
        self.assertEqual(data["total_requests"], 0)
        self.assertEqual(data["recent_failures"], [])

    def test_activity_range_uses_request_date_and_limits_failures(self):
        now = datetime(2026, 9, 28, 12, tzinfo=UTC)
        self.add_log(1, datetime(2026, 9, 21, 23, 59), 200, "old", 50)
        self.add_log(2, datetime(2026, 9, 22, 0, 0), 200, "chat", 10)
        self.add_log(3, datetime(2026, 9, 28, 23, 59), 500, "chat")
        for identifier in range(4, 10):
            self.add_log(identifier, datetime(2026, 9, 28, 11, identifier), 429, "embed")
        result = get_overview_activity(self.db, 7, now)
        self.assertEqual(result.total_requests, 8)
        self.assertEqual(result.successful_requests, 1)
        self.assertEqual(result.total_tokens, 10)
        self.assertEqual(result.daily[0].date, "2026-09-22")
        self.assertEqual(result.daily[-1].requests, 7)
        self.assertEqual([item.name for item in result.top_models], ["embed", "chat"])
        self.assertEqual(len(result.recent_failures), 5)
        self.assertEqual(result.recent_failures[0].request_id, "request-3")


if __name__ == "__main__":
    unittest.main()
