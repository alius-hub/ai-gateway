import hashlib
import json
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

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
    AggregatedModel,
    ApiKey,
    Organization,
    Project,
    ProjectMember,
    Provider,
    ProviderModel,
    ProviderProtocol,
    ProviderSecret,
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


class CredentialApiTest(unittest.TestCase):
    def setUp(self):
        self.encryption_key = Fernet.generate_key().decode()
        self.settings_patch = patch(
            "app.modules.credential.router.get_settings",
            return_value=SimpleNamespace(provider_encryption_key=self.encryption_key),
        )
        self.settings_patch.start()
        self.engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine, tables=[
            User.__table__, Organization.__table__, Project.__table__, ProjectMember.__table__,
            Provider.__table__,
            ProviderProtocol.__table__, ProviderSecret.__table__, ProviderModel.__table__,
            AggregatedModel.__table__, ApiKey.__table__, UsageRecord.__table__,
        ])
        self.db = Session(self.engine)
        self.db.add_all([
            User(id=1, username="admin", email="admin@example.com",
                 password_hash="hash", is_platform_admin=1),
            User(id=2, username="member", email="member@example.com", password_hash="hash"),
            Project(id=1, organization_id=None, name="Platform", code="platform", owner_user_id=1),
            Provider(id=1, name="Example", code="example", provider_type="openai",
                     base_url="https://example.com"),
            ProviderModel(id=1, provider_id=1, access_model_code="model-1",
                          provider_model_name="model-1", model_type="llm", currency="USD"),
            AggregatedModel(id=1, aggregate_model_code="aggregate-1", public_model_name="chat-pro",
                            model_type="llm", default_routing_strategy="single",
                            routing_model_ids=[1], status=1),
        ])
        self.db.commit()
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.admin = {"Authorization": f"Bearer {create_access_token('1')}"}
        self.member = {"Authorization": f"Bearer {create_access_token('2')}"}

    def tearDown(self):
        self.settings_patch.stop()
        app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()

    def payload(self):
        return {
            "name": "Test key", "aggregate_model_ids": [1], "access_model_ids": [1],
            "tpm_limit": 1200, "qps_limit": 5, "token_budget": 10000,
            "budget_period": "week", "wait_mode": "queue", "max_wait_ms": 20000,
        }

    def test_project_key_lifecycle_and_platform_project(self):
        path = "/api/admin/v1/credentials/project-keys"
        payload = {**self.payload(), "project_id": 1}
        self.assertEqual(self.client.post(path, json=payload, headers=self.member).status_code, 403)
        created = self.client.post(path, json=payload, headers=self.admin)
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.headers["cache-control"], "no-store")
        result = created.json()["data"]
        raw = result["api_key"]
        self.assertTrue(raw.startswith("agw_"))
        self.assertNotIn("key_hash", created.text)
        stored = self.db.get(ApiKey, result["id"])
        self.assertIsNone(stored.organization_id)
        self.assertEqual(stored.key_hash, hashlib.sha256(raw.encode()).hexdigest())
        self.assertEqual(Fernet(self.encryption_key.encode()).decrypt(
            stored.key_ciphertext.encode()).decode(), raw)
        self.assertNotIn(raw, stored.key_ciphertext)
        self.assertEqual(stored.allowed_models, {"aggregate_ids": [1], "access_ids": [1]})
        self.assertTrue(result["revealable"])

        listed = self.client.get(path, headers=self.admin)
        self.assertEqual(listed.json()["data"]["total"], 1)
        filtered = self.client.get(path, headers=self.admin, params={
            "filters": json.dumps({"mode": "and", "conditions": [
                {"field": "name", "operator": "contains", "value": "Test"},
                {"field": "qps_limit", "operator": "eq", "value": "5"},
            ]}),
        })
        self.assertEqual(filtered.status_code, 200, filtered.text)
        self.assertEqual(filtered.json()["data"]["total"], 1)
        self.assertEqual(self.client.get(path, headers=self.member, params={
            "filters": json.dumps({"mode": "and", "conditions": [
                {"field": "name", "operator": "eq", "value": "Test key"},
            ]}),
        }).status_code, 403)
        self.assertNotIn(raw, listed.text)
        self.assertNotIn(stored.key_ciphertext, listed.text)
        denied = self.client.get(f"{path}/{stored.id}", headers=self.member)
        self.assertEqual(denied.status_code, 403)
        revealed = self.client.get(f"{path}/{stored.id}/secret", headers=self.admin)
        self.assertEqual(revealed.status_code, 200)
        self.assertEqual(revealed.headers["cache-control"], "no-store")
        self.assertEqual(revealed.json()["data"]["api_key"], raw)
        self.assertIn({"id": "chat-pro", "model_type": "llm"}, revealed.json()["data"]["models"])
        self.assertEqual(self.client.get(f"{path}/{stored.id}/secret", headers=self.admin
                                         ).json()["data"]["api_key"], raw)
        self.assertEqual(self.client.get(f"{path}/{stored.id}/secret", headers=self.member
                                         ).status_code, 403)
        self.assertEqual(self.client.get(
            f"/api/admin/v1/credentials/user-keys/{stored.id}/secret", headers=self.admin,
        ).status_code, 404)
        updated = self.client.put(f"{path}/{stored.id}", json={
            **self.payload(), "name": "Changed", "wait_mode": "block",
        }, headers=self.admin)
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertNotIn(raw, updated.text)
        self.assertNotIn(stored.key_ciphertext, updated.text)
        rotated = self.client.post(f"{path}/{stored.id}/rotate", headers=self.admin)
        self.assertEqual(rotated.status_code, 200, rotated.text)
        self.assertEqual(rotated.headers["cache-control"], "no-store")
        self.assertNotEqual(rotated.json()["data"]["api_key"], raw)
        self.assertNotEqual(stored.key_hash, hashlib.sha256(raw.encode()).hexdigest())
        revealed_after_rotation = self.client.get(
            f"{path}/{stored.id}/secret", headers=self.admin,
        ).json()["data"]["api_key"]
        self.assertEqual(revealed_after_rotation, rotated.json()["data"]["api_key"])
        disabled = self.client.patch(f"{path}/{stored.id}/status",
                                     json={"status": 0}, headers=self.admin)
        self.assertEqual(disabled.json()["data"]["status"], 0)

    def test_project_key_optional_owner_must_be_active_project_member(self):
        path = "/api/admin/v1/credentials/project-keys"
        payload = {**self.payload(), "project_id": 1}
        unassigned = self.client.post(path, json=payload, headers=self.admin)
        self.assertEqual(unassigned.status_code, 201, unassigned.text)
        self.assertIsNone(unassigned.json()["data"]["user_id"])
        self.assertEqual(self.client.post(
            path, json={**payload, "user_id": 2}, headers=self.admin,
        ).status_code, 422)
        self.db.add(Project(id=2, name="Other", code="other", owner_user_id=1))
        self.db.add(ProjectMember(project_id=2, user_id=2, role="developer", status=1))
        self.db.commit()
        self.assertEqual(self.client.post(
            path, json={**payload, "user_id": 2}, headers=self.admin,
        ).status_code, 422)
        self.db.add(ProjectMember(project_id=1, user_id=2, role="developer", status=1))
        self.db.commit()
        created = self.client.post(path, json={**payload, "user_id": 2}, headers=self.admin)
        self.assertEqual(created.status_code, 201, created.text)
        key_id = created.json()["data"]["id"]
        self.assertEqual(self.db.get(ApiKey, key_id).user_id, 2)
        listed = self.client.get(path, headers=self.admin).json()["data"]["items"][0]
        self.assertEqual(listed["owner_name"], "member")
        summary = self.client.get("/api/admin/v1/projects/1/keys",
                                  headers=self.admin).json()["data"]["items"][0]
        self.assertEqual(summary["owner_name"], "member")
        self.assertEqual(summary["creator_name"], "admin")
        member = self.db.query(ProjectMember).filter_by(project_id=1).one()
        member.status = 0
        self.db.commit()
        self.assertEqual(self.client.post(
            path, json={**payload, "user_id": 2}, headers=self.admin,
        ).status_code, 422)
        self.client.patch(f"{path}/{key_id}/status", json={"status": 0}, headers=self.admin)
        self.assertEqual(self.client.patch(
            f"{path}/{key_id}/status", json={"status": 1}, headers=self.admin,
        ).status_code, 422)
        member.status = 1
        self.db.get(User, 2).status = 0
        self.db.commit()
        self.assertEqual(self.client.post(
            path, json={**payload, "user_id": 2}, headers=self.admin,
        ).status_code, 422)
        self.assertEqual(self.client.post(
            path, json={**payload, "user_id": 999}, headers=self.admin,
        ).status_code, 422)
        self.assertEqual(self.client.post("/api/admin/v1/credentials/user-keys", json={
            **self.payload(), "user_id": 1, "project_id": 1,
        }, headers=self.admin).status_code, 422)

    def test_personal_key_and_invalid_binding_or_budget(self):
        path = "/api/admin/v1/credentials/user-keys"
        created = self.client.post(path, json={**self.payload(), "user_id": 2}, headers=self.admin)
        self.assertEqual(created.status_code, 201, created.text)
        self.assertIsNone(created.json()["data"]["organization_id"])
        self.assertEqual(self.client.get(path, headers=self.member).status_code, 403)
        invalid = [
            {**self.payload(), "user_id": 2, "aggregate_model_ids": [], "access_model_ids": []},
            {**self.payload(), "user_id": 2, "aggregate_model_ids": [999]},
            {**self.payload(), "user_id": 2, "budget_period": None},
            {**self.payload(), "user_id": 2, "project_id": 1},
        ]
        for payload in invalid:
            with self.subTest(payload=payload):
                response = self.client.post(path, json=payload, headers=self.admin)
                self.assertEqual(response.status_code, 422)

    def test_legacy_key_needs_rotation_without_breaking_hash(self):
        path = "/api/admin/v1/credentials/user-keys"
        created = self.client.post(path, json={**self.payload(), "user_id": 2},
                                   headers=self.admin).json()["data"]
        item = self.db.get(ApiKey, created["id"])
        original_hash = item.key_hash
        item.key_ciphertext = None
        self.db.commit()
        self.assertEqual(self.client.get(f"{path}/{item.id}/secret",
                                         headers=self.admin).status_code, 409)
        self.assertEqual(self.db.get(ApiKey, item.id).key_hash, original_hash)
        self.assertFalse(self.client.get(path, headers=self.admin
                                         ).json()["data"]["items"][0]["revealable"])
        rotated = self.client.post(f"{path}/{item.id}/rotate", headers=self.admin)
        self.assertEqual(rotated.status_code, 200)
        self.assertNotEqual(item.key_hash, original_hash)
        revealed_after_rotation = self.client.get(
            f"{path}/{item.id}/secret", headers=self.admin,
        ).json()["data"]["api_key"]
        self.assertEqual(revealed_after_rotation, rotated.json()["data"]["api_key"])

    def test_invalid_encryption_configuration_does_not_save_or_reveal_key(self):
        path = "/api/admin/v1/credentials/project-keys"
        with patch("app.modules.credential.router.get_settings",
                   return_value=SimpleNamespace(provider_encryption_key="")):
            response = self.client.post(path, json={**self.payload(), "project_id": 1},
                                        headers=self.admin)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.db.query(ApiKey).count(), 0)
        created = self.client.post(path, json={**self.payload(), "project_id": 1},
                                   headers=self.admin).json()["data"]
        with patch("app.modules.credential.router.get_settings",
                   return_value=SimpleNamespace(provider_encryption_key=Fernet.generate_key().decode())):
            response = self.client.get(f"{path}/{created['id']}/secret", headers=self.admin)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(created["api_key"], response.text)

    def test_custom_prefix_creation_rotation_and_default(self):
        path = "/api/admin/v1/credentials/project-keys"
        created = self.client.post(path, json={
            **self.payload(), "project_id": 1, "custom_prefix": "team-prod",
        }, headers=self.admin)
        self.assertEqual(created.status_code, 201, created.text)
        result = created.json()["data"]
        self.assertTrue(result["api_key"].startswith("team-prod_"))
        self.assertEqual(result["custom_prefix"], "team-prod")
        stored = self.db.get(ApiKey, result["id"])
        self.assertEqual(stored.custom_prefix, "team-prod")
        self.assertTrue(stored.key_prefix.startswith("team-prod_"))
        self.assertEqual(stored.key_hash, hashlib.sha256(result["api_key"].encode()).hexdigest())
        self.assertEqual(self.client.get(f"{path}/{stored.id}/secret", headers=self.admin
                                         ).json()["data"]["api_key"], result["api_key"])

        preserved = self.client.post(f"{path}/{stored.id}/rotate", headers=self.admin)
        self.assertEqual(preserved.status_code, 200, preserved.text)
        self.assertTrue(preserved.json()["data"]["api_key"].startswith("team-prod_"))
        changed = self.client.post(f"{path}/{stored.id}/rotate",
                                   json={"custom_prefix": "other_"}, headers=self.admin)
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertTrue(changed.json()["data"]["api_key"].startswith("other_"))
        self.assertEqual(changed.json()["data"]["custom_prefix"], "other_")
        reset = self.client.post(f"{path}/{stored.id}/rotate",
                                 json={"custom_prefix": None}, headers=self.admin)
        self.assertEqual(reset.status_code, 200, reset.text)
        self.assertTrue(reset.json()["data"]["api_key"].startswith("agw_"))
        self.assertIsNone(reset.json()["data"]["custom_prefix"])

        default = self.client.post("/api/admin/v1/credentials/user-keys", json={
            **self.payload(), "user_id": 2, "custom_prefix": "",
        }, headers=self.admin)
        self.assertEqual(default.status_code, 201, default.text)
        self.assertTrue(default.json()["data"]["api_key"].startswith("agw_"))
        self.assertIsNone(default.json()["data"]["custom_prefix"])

    def test_invalid_custom_prefix_does_not_create_or_rotate_key(self):
        path = "/api/admin/v1/credentials/user-keys"
        for prefix in ("a", "1team", "with space", "bad!", "中文", "a" * 21, "_app", " team"):
            with self.subTest(prefix=prefix):
                response = self.client.post(path, json={
                    **self.payload(), "user_id": 2, "custom_prefix": prefix,
                }, headers=self.admin)
                self.assertEqual(response.status_code, 422)
        self.assertEqual(self.db.query(ApiKey).count(), 0)
        created = self.client.post(path, json={
            **self.payload(), "user_id": 2, "custom_prefix": "good",
        }, headers=self.admin).json()["data"]
        original_hash = self.db.get(ApiKey, created["id"]).key_hash
        invalid = self.client.post(f"{path}/{created['id']}/rotate",
                                   json={"custom_prefix": "bad!"}, headers=self.admin)
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(self.db.get(ApiKey, created["id"]).key_hash, original_hash)

    def test_project_key_overview_usage_pagination_and_access(self):
        path = "/api/admin/v1/projects/1/keys"
        self.db.get(Project, 1).owner_user_id = 2
        self.db.add(Project(id=2, name="Other", code="other", owner_user_id=1))
        self.db.get(Project, 1).amount_budget = Decimal("100.00")
        self.db.commit()
        first = self.client.post("/api/admin/v1/credentials/project-keys", json={
            **self.payload(), "project_id": 1, "amount_budget": 10,
        }, headers=self.admin).json()["data"]
        second = self.client.post("/api/admin/v1/credentials/project-keys", json={
            **self.payload(), "project_id": 1, "budget_period": "month",
            "token_budget": 5000, "amount_budget": 20,
        }, headers=self.admin).json()["data"]
        other = self.client.post("/api/admin/v1/credentials/project-keys", json={
            **self.payload(), "project_id": 2,
        }, headers=self.admin).json()["data"]
        now = datetime.now(UTC).replace(tzinfo=None)
        self.db.get(ApiKey, second["id"]).expires_at = now - timedelta(days=1)
        last_month = now - timedelta(days=40)
        self.db.add_all([
            UsageRecord(request_log_id=1, project_id=1, api_key_id=first["id"], model_type="llm",
                        total_tokens=120, estimated_cost=Decimal("1.20"),
                        currency="CNY", created_at=now),
            UsageRecord(request_log_id=2, project_id=1, api_key_id=first["id"], model_type="llm",
                        total_tokens=30, estimated_cost=Decimal("2.00"),
                        currency="CNY", created_at=last_month),
            UsageRecord(request_log_id=3, project_id=1, api_key_id=second["id"], model_type="llm",
                        total_tokens=50, estimated_cost=Decimal("9.00"),
                        currency="USD", created_at=now),
            UsageRecord(request_log_id=4, project_id=2, api_key_id=other["id"], model_type="llm",
                        total_tokens=500, estimated_cost=Decimal("5.00"),
                        currency="CNY", created_at=now),
        ])
        self.db.commit()
        response = self.client.get(path, headers=self.member, params={"page_size": 1, "page": 2})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["project_amount_budget"], "100.00")
        self.assertEqual(Decimal(str(data["project_total_cost"])), Decimal("3.20"))
        key = data["items"][0]
        self.assertEqual(key["id"], first["id"])
        self.assertEqual(key["creator_name"], "admin")
        self.assertEqual(key["total_tokens"], 150)
        self.assertEqual(Decimal(str(key["total_cost"])), Decimal("3.20"))
        self.assertEqual(key["period_tokens"], 120)
        self.assertEqual(Decimal(str(key["period_cost"])), Decimal("1.20"))
        self.assertNotIn(first["api_key"], response.text)
        self.assertNotIn("key_ciphertext", response.text)
        monthly_page = self.client.get(path, headers=self.member, params={"page_size": 1})
        monthly = monthly_page.json()["data"]["items"][0]
        self.assertEqual(monthly["id"], second["id"])
        self.assertTrue(monthly["expires_at"].endswith("Z"))
        self.assertEqual(monthly["period_tokens"], 50)
        self.assertEqual(Decimal(str(monthly["period_cost"])), Decimal("0"))
        self.assertEqual(self.client.get("/api/admin/v1/projects/2/keys",
                                         headers=self.member).status_code, 403)
        self.assertEqual(self.client.get("/api/admin/v1/projects/999/keys",
                                         headers=self.admin).status_code, 404)


if __name__ == "__main__":
    unittest.main()
