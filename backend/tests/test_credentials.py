import hashlib
import unittest
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
    Provider,
    ProviderModel,
    ProviderProtocol,
    ProviderSecret,
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
            User.__table__, Organization.__table__, Project.__table__, Provider.__table__,
            ProviderProtocol.__table__, ProviderSecret.__table__, ProviderModel.__table__,
            AggregatedModel.__table__, ApiKey.__table__,
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


if __name__ == "__main__":
    unittest.main()
