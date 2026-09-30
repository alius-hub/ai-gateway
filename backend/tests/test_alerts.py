import json
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token
from app.db.base import Base
from app.db.models import (
    AlertDelivery,
    AlertEvent,
    AlertRule,
    FeishuSettings,
    RequestLog,
    User,
)
from app.db.session import get_db
from app.main import app
from app.modules.alerts import deliver_alerts, evaluate_alerts, send_feishu


@compiles(BigInteger, "sqlite")
def sqlite_bigint(_type, _compiler, **_kwargs):
    return "INTEGER"


@compiles(JSONB, "sqlite")
def sqlite_jsonb(_type, _compiler, **_kwargs):
    return "JSON"


class AlertsTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine, tables=[
            User.__table__, RequestLog.__table__, FeishuSettings.__table__,
            AlertRule.__table__, AlertEvent.__table__, AlertDelivery.__table__,
        ])
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
        self.key = Fernet.generate_key().decode()
        self.settings = patch("app.modules.alerts.get_settings", return_value=SimpleNamespace(
            provider_encryption_key=self.key,
        ))
        self.settings.start()

    def tearDown(self):
        self.settings.stop()
        app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()

    def test_feishu_credentials_and_permissions(self):
        url = "/api/admin/v1/alerts/settings/feishu"
        payload = {"app_id": "cli_test", "app_secret": "private-value",
                   "chat_id": "oc_test", "enabled": True}
        self.assertEqual(self.client.put(url, json=payload).status_code, 401)
        self.assertEqual(self.client.put(url, json=payload, headers=self.member).status_code, 403)
        self.assertEqual(self.client.put(url, json=payload, headers=self.admin).status_code, 200)
        self.assertNotIn("private-value", str(self.client.get(url, headers=self.admin).json()))
        self.assertTrue(self.client.get(url, headers=self.admin).json()["data"]["has_secret"])
        self.assertNotIn("private-value", self.db.get(FeishuSettings, 1).app_secret_ciphertext)
        self.assertEqual(self.client.put(url, json={
            "app_id": "cli_new", "chat_id": "oc_new", "enabled": True,
        }, headers=self.admin).status_code, 200)
        self.assertEqual(Fernet(self.key).decrypt(
            self.db.get(FeishuSettings, 1).app_secret_ciphertext.encode()
        ).decode(), "private-value")
        with patch("app.modules.alerts.send_feishu") as send:
            self.assertEqual(self.client.post(url + "/test", headers=self.admin).status_code, 200)
            send.assert_called_once_with("cli_new", "private-value", "oc_new",
                                         "AI Gateway 告警中心：飞书消息测试成功。")

    def test_evaluation_deduplication_recovery_and_retry(self):
        url = "/api/admin/v1/alerts/rules"
        payload = {
            "name": "平台上游错误率", "metric": "error_rate", "scope_id": None,
            "threshold": 50, "window_minutes": 5, "min_samples": 2,
            "level": "critical", "enabled": True,
        }
        created = self.client.post(url, json=payload, headers=self.admin)
        self.assertEqual(created.status_code, 201)
        rule_id = created.json()["data"]["id"]
        now = datetime(2026, 9, 29, 12, tzinfo=UTC)
        for idx, code in enumerate((500, 503, 202, 429)):
            self.db.add(RequestLog(
                id=idx + 1, request_id=f"test-{idx}", public_model_name="test",
                model_type="llm", endpoint="/v1/chat/completions", requester_ip="127.0.0.1",
                http_status=code, created_at=(now - timedelta(minutes=1)).replace(tzinfo=None),
            ))
        self.db.commit()
        evaluate_alerts(self.db, now)
        evaluate_alerts(self.db, now)
        self.assertEqual(self.db.query(AlertEvent).count(), 1)
        event = self.db.query(AlertEvent).one()
        self.assertEqual(event.current_value, 100)
        self.assertEqual(self.db.query(AlertDelivery).count(), 1)
        self.db.add(FeishuSettings(
            id=1, app_id="cli_test", chat_id="oc_test", enabled=True,
            app_secret_ciphertext=Fernet(self.key).encrypt(b"secret").decode(),
        ))
        self.db.commit()
        calls = 0

        def send_without_transaction(*_args):
            nonlocal calls
            self.assertFalse(self.db.in_transaction())
            calls += 1
            if calls == 1:
                raise ValueError("bad")

        with patch("app.modules.alerts.send_feishu", side_effect=send_without_transaction) as send:
            deliver_alerts(self.db, now)
            delivery = self.db.query(AlertDelivery).one()
            self.assertEqual(delivery.attempts, 1)
            deliver_alerts(self.db, now + timedelta(minutes=2))
            self.assertEqual(delivery.status, "sent")
            self.assertEqual(send.call_count, 2)
        self.assertEqual(self.client.post(
            f"/api/admin/v1/alerts/events/{event.id}/ack", headers=self.admin,
        ).status_code, 200)
        self.db.query(RequestLog).filter(RequestLog.http_status >= 500).update(
            {"http_status": 200},
        )
        self.db.commit()
        evaluate_alerts(self.db, now)
        self.assertEqual(event.status, "resolved")
        self.assertEqual(self.db.query(AlertDelivery).count(), 2)
        self.assertEqual(self.client.get(
            "/api/admin/v1/alerts/events", headers=self.admin,
        ).json()["data"]["total"], 1)
        self.assertEqual(self.client.delete(
            f"{url}/{rule_id}", headers=self.admin,
        ).status_code, 409)

    def test_idle_window_resolves_error_rate_incident(self):
        rule = AlertRule(name="错误率", metric="error_rate", threshold=50,
                         window_minutes=5, min_samples=2, level="warning", enabled=True)
        self.db.add(rule)
        now = datetime(2026, 9, 29, 12, tzinfo=UTC)
        self.db.add_all(RequestLog(
            request_id=f"idle-{idx}", public_model_name="test", model_type="llm",
            endpoint="/v1/chat/completions", requester_ip="127.0.0.1",
            http_status=500, created_at=(now - timedelta(minutes=1)).replace(tzinfo=None),
        ) for idx in range(2))
        self.db.commit()
        evaluate_alerts(self.db, now)
        event = self.db.query(AlertEvent).one()
        evaluate_alerts(self.db, now + timedelta(minutes=6))
        self.assertEqual(event.status, "resolved")
        self.assertEqual(self.db.query(AlertDelivery).count(), 2)

    def test_bot_discovers_unique_chat_and_rejects_ambiguous_target(self):
        client = MagicMock()
        token = MagicMock()
        token.json.return_value = {"code": 0, "tenant_access_token": "token"}
        sent = MagicMock()
        sent.json.return_value = {"code": 0}
        client.post.side_effect = [token, sent]
        client.get.return_value.json.return_value = {
            "code": 0, "data": {"items": [{"chat_id": "oc_unique"}], "has_more": False},
        }
        with patch("app.modules.alerts.httpx.Client") as factory:
            factory.return_value.__enter__.return_value = client
            send_feishu("app", "secret", "", "message")
            self.assertEqual(client.post.call_args.kwargs["json"]["receive_id"], "oc_unique")
            client.post.reset_mock(side_effect=True)
            client.post.return_value = token
            client.get.return_value.json.return_value = {
                "code": 0, "data": {"items": [{"chat_id": "one"}, {"chat_id": "two"}]},
            }
            with self.assertRaisesRegex(ValueError, "多个群聊"):
                send_feishu("app", "secret", "", "message")
            self.assertEqual(client.post.call_count, 1)
            client.get.reset_mock()
            client.post.side_effect = [token, sent]
            send_feishu("app", "secret", "ou_private", "message", "open_id")
            client.get.assert_not_called()
            self.assertEqual(client.post.call_args.kwargs["params"],
                             {"receive_id_type": "open_id"})
            self.assertEqual(client.post.call_args.kwargs["json"]["receive_id"], "ou_private")

    def test_rule_targets_are_isolated_snapshotted_and_retry_independently(self):
        now = datetime(2026, 9, 30, 12, tzinfo=UTC)
        targets = [
            {"receive_id_type": "open_id", "receive_id": "ou_one"},
            {"receive_id_type": "open_id", "receive_id": "ou_two"},
            {"receive_id_type": "chat_id", "receive_id": "oc_one"},
        ]
        first = AlertRule(name="first", metric="error_rate", threshold=50,
                          min_samples=1, recipients=targets)
        second = AlertRule(name="second", metric="error_rate", threshold=50,
                           min_samples=1,
                           recipients=[{"receive_id_type": "chat_id", "receive_id": "oc_two"}])
        self.db.add_all([first, second, FeishuSettings(
            id=1, app_id="app", chat_id="unused", enabled=True,
            app_secret_ciphertext=Fernet(self.key).encrypt(b"secret").decode(),
        ), RequestLog(
            request_id="multi", public_model_name="test", model_type="llm",
            endpoint="/v1/chat/completions", requester_ip="127.0.0.1", http_status=500,
            created_at=(now - timedelta(minutes=1)).replace(tzinfo=None),
        )])
        self.db.commit()
        evaluate_alerts(self.db, now)
        self.assertEqual(self.db.query(AlertDelivery).count(), 4)
        first.recipients = [{"receive_id_type": "chat_id", "receive_id": "oc_changed"}]
        self.db.commit()
        with patch("app.modules.alerts.send_feishu", side_effect=[ValueError("failed"),
                                                                None, None, None]) as send:
            deliver_alerts(self.db, now)
            destinations = {(call.args[4], call.args[2]) for call in send.call_args_list}
            self.assertEqual(destinations, {("open_id", "ou_one"), ("open_id", "ou_two"),
                                            ("chat_id", "oc_one"), ("chat_id", "oc_two")})
        self.assertEqual(self.db.query(AlertDelivery).filter_by(status="sent").count(), 3)
        with patch("app.modules.alerts.send_feishu") as send:
            deliver_alerts(self.db, now + timedelta(minutes=2))
            self.assertEqual(send.call_count, 1)
        evaluate_alerts(self.db, now + timedelta(minutes=6))
        recovery = self.db.query(AlertDelivery).filter_by(kind="resolved").all()
        self.assertEqual({item.receive_id for item in recovery},
                         {"ou_one", "ou_two", "oc_one", "oc_two"})
        duplicate = {"name": "duplicate", "metric": "error_rate", "threshold": 10,
                     "recipients": [targets[0], targets[0]]}
        self.assertEqual(self.client.post("/api/admin/v1/alerts/rules", json=duplicate,
                                          headers=self.admin).status_code, 422)

    def test_advanced_filters_apply_before_pagination_and_reject_unknown_fields(self):
        now = datetime(2026, 9, 30, 12, tzinfo=UTC)
        rules = [
            AlertRule(name="critical rule", metric="error_rate", threshold=50,
                      level="critical", enabled=True),
            AlertRule(name="resolved rule", metric="error_rate", threshold=20,
                      level="warning", enabled=True),
            AlertRule(name="disabled rule", metric="error_rate", threshold=60,
                      level="warning", enabled=False),
        ]
        self.db.add_all(rules)
        self.db.flush()
        for rule, value, status in zip(rules, (100, 10, 90), ("open", "resolved", "open"),
                                       strict=True):
            self.db.add(AlertEvent(rule_id=rule.id, current_value=value, threshold=rule.threshold,
                                   triggered_at=now, status=status))
        self.db.commit()
        base = "/api/admin/v1/alerts"
        group = {"mode": "and", "conditions": [
            {"field": "level", "operator": "eq", "value": "warning"},
            {"field": "enabled", "operator": "eq", "value": "0"},
        ]}
        result = self.client.get(base + "/rules", params={"filters": json.dumps(group)},
                                 headers=self.admin)
        self.assertEqual(result.status_code, 200)
        self.assertEqual([item["name"] for item in result.json()["data"]], ["disabled rule"])
        rule_group = {"mode": "and", "conditions": [
            {"field": "level", "operator": "eq", "value": "warning"},
        ]}
        for page, expected in ((1, "disabled rule"), (2, "resolved rule")):
            result = self.client.get(base + "/rules", params={
                "filters": json.dumps(rule_group), "page": page, "page_size": 1,
            }, headers=self.admin)
            self.assertEqual(result.status_code, 200)
            data = result.json()["data"]
            self.assertEqual(data["total"], 2)
            self.assertEqual(data["page"], page)
            self.assertEqual(data["page_size"], 1)
            self.assertEqual([item["name"] for item in data["items"]], [expected])
        for params in ({"page": 0}, {"page": 1, "page_size": 101}):
            self.assertEqual(self.client.get(base + "/rules", params=params,
                                             headers=self.admin).status_code, 422)
        group = {"mode": "or", "conditions": [
            {"field": "level", "operator": "eq", "value": "critical"},
            {"field": "current_value", "operator": "gt", "value": "80"},
        ]}
        result = self.client.get(base + "/events", params={
            "filters": json.dumps(group), "status": "open", "page_size": 1,
        }, headers=self.admin)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["data"]["total"], 2)
        self.assertEqual(len(result.json()["data"]["items"]), 1)
        group = {"mode": "and", "conditions": [
            {"field": "triggered_at", "operator": "eq", "value": "2026-09-30"},
            {"field": "rule_name", "operator": "contains", "value": "resolved"},
        ]}
        result = self.client.get(base + "/events", params={"filters": json.dumps(group)},
                                 headers=self.admin)
        self.assertEqual(result.json()["data"]["total"], 1)
        invalid = {"mode": "and", "conditions": [
            {"field": "app_secret", "operator": "contains", "value": "secret"},
        ]}
        for endpoint in ("rules", "events"):
            self.assertEqual(self.client.get(base + "/" + endpoint,
                                              params={"filters": json.dumps(invalid)},
                                              headers=self.admin).status_code, 422)

    def test_rule_test_push_reports_each_target_without_creating_incidents(self):
        targets = [{"receive_id_type": "open_id", "receive_id": "ou_test"},
                   {"receive_id_type": "chat_id", "receive_id": "oc_test"}]
        rule = AlertRule(name="测试规则", metric="error_rate", threshold=50,
                         recipients=targets, enabled=False)
        self.db.add(rule)
        self.db.commit()
        url = f"/api/admin/v1/alerts/rules/{rule.id}/test"
        self.assertEqual(self.client.post(url).status_code, 401)
        self.assertEqual(self.client.post(url, headers=self.member).status_code, 403)
        self.assertEqual(self.client.post(url, headers=self.admin).status_code, 422)
        self.db.add(FeishuSettings(
            id=1, app_id="app", chat_id="oc_default", enabled=False,
            app_secret_ciphertext=Fernet(self.key).encrypt(b"secret").decode(),
        ))
        self.db.commit()

        def send_test(_app, _secret, target, message, _type):
            self.assertFalse(self.db.in_transaction())
            self.assertIn("测试推送", message)
            if target == "ou_test":
                raise ValueError("用户不在可用范围")

        with patch("app.modules.alerts.send_feishu", side_effect=send_test) as send:
            response = self.client.post(url, headers=self.admin)
            self.assertEqual(response.status_code, 200)
            results = response.json()["data"]["results"]
            self.assertEqual([item["sent"] for item in results], [False, True])
            self.assertEqual(results[0]["error"], "用户不在可用范围")
            self.assertEqual(send.call_count, 2)
        self.assertEqual(self.db.query(AlertEvent).count(), 0)
        self.assertEqual(self.db.query(AlertDelivery).count(), 0)
        rule.recipients = []
        self.db.commit()
        with patch("app.modules.alerts.send_feishu") as send:
            self.assertEqual(self.client.post(url, headers=self.admin).status_code, 200)
            self.assertEqual(send.call_args.args[2], "oc_default")
        self.assertEqual(self.client.post("/api/admin/v1/alerts/rules/999/test",
                                          headers=self.admin).status_code, 404)

    def test_manual_recovery_rearms_only_after_value_falls(self):
        rule = AlertRule(name="错误率", metric="error_rate", threshold=50,
                         window_minutes=5, min_samples=1, level="warning", enabled=True)
        self.db.add(rule)
        now = datetime.now(UTC).replace(microsecond=0)
        log = RequestLog(request_id="manual-1", public_model_name="test", model_type="llm",
                         endpoint="/v1/chat/completions", requester_ip="127.0.0.1",
                         http_status=500,
                         created_at=(now - timedelta(minutes=1)).replace(tzinfo=None))
        self.db.add(log)
        self.db.commit()
        evaluate_alerts(self.db, now)
        event = self.db.query(AlertEvent).one()
        self.assertEqual(self.client.post(
            f"/api/admin/v1/alerts/events/{event.id}/resolve", headers=self.admin,
        ).status_code, 200)
        evaluate_alerts(self.db, now)
        self.assertEqual(self.db.query(AlertEvent).count(), 1)
        log.http_status = 200
        self.db.commit()
        evaluate_alerts(self.db, now)
        self.assertFalse(rule.suppressed_until_recovery)
        log.http_status = 500
        self.db.commit()
        evaluate_alerts(self.db, now)
        self.assertEqual(self.db.query(AlertEvent).count(), 2)


if __name__ == "__main__":
    unittest.main()
