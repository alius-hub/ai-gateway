import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token
from app.db.base import Base
from app.db.models import Provider, ProviderModel, ProviderProtocol, ProviderSecret, User
from app.db.session import get_db
from app.main import app


@compiles(BigInteger, "sqlite")
def compile_bigint_for_sqlite(_type, _compiler, **_kwargs):
    return "INTEGER"


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


class ProviderApiTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(self.engine, tables=[
            User.__table__, Provider.__table__, ProviderProtocol.__table__,
            ProviderSecret.__table__, ProviderModel.__table__,
        ])
        self.db = Session(self.engine)
        self.db.add_all([
            User(id=1, username="admin", email="admin@example.com",
                 password_hash="hash", is_platform_admin=1),
            User(id=2, username="viewer", email="viewer@example.com", password_hash="hash"),
        ])
        self.db.commit()
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.path = "/api/admin/v1/providers"
        self.admin = {"Authorization": f"Bearer {create_access_token('1')}"}
        self.viewer = {"Authorization": f"Bearer {create_access_token('2')}"}
        self.key = Fernet.generate_key().decode()
        self.settings_patch = patch(
            "app.modules.provider.router.get_settings",
            return_value=SimpleNamespace(provider_encryption_key=self.key),
        )
        self.settings_patch.start()

    def tearDown(self):
        self.settings_patch.stop()
        app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()

    def test_create_update_list_and_status_without_exposing_key(self):
        payload = {
            "name": "Example", "code": "example", "provider_type": "openai_compatible",
            "base_url": "https://api.example.com/v1", "api_key": "secret-value",
        }
        self.assertEqual(self.client.post(self.path, json=payload, headers=self.viewer).status_code, 403)
        created = self.client.post(self.path, json=payload, headers=self.admin)
        self.assertEqual(created.status_code, 201, created.text)
        item = created.json()["data"]
        self.assertNotIn("secret-value", created.text)
        secret = self.db.query(ProviderSecret).filter_by(provider_id=item["id"]).one()
        self.assertEqual(Fernet(self.key).decrypt(secret.ciphertext.encode()), b"secret-value")
        encrypted = secret.ciphertext
        self.assertIsNone(self.db.get(Provider, item["id"]).api_key_ciphertext)
        self.assertEqual(self.client.post(self.path, json=payload, headers=self.admin).status_code, 409)
        listed = self.client.get(self.path, params={"keyword": "EXAM", "page_size": 1},
                                 headers=self.viewer)
        self.assertEqual(listed.json()["data"]["total"], 1)
        self.assertEqual(len(listed.json()["data"]["items"]), 1)
        updated = self.client.patch(f"{self.path}/{item['id']}", json={"name": "New"},
                                    headers=self.admin)
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(secret.ciphertext, encrypted)
        self.assertEqual(self.client.patch(f"{self.path}/{item['id']}/status",
                                          json={"status": 0}, headers=self.viewer).status_code, 403)
        self.assertEqual(self.client.patch(f"{self.path}/{item['id']}/status",
                                          json={"status": 0}, headers=self.admin).json()["data"]["status"], 0)
        self.assertEqual(self.client.get(f"{self.path}/{item['id']}/health",
                                         headers=self.viewer).json()["data"]["health_status"], "unknown")

    def test_multiple_connections_and_model_ownership(self):
        def provider(code):
            return self.client.post(self.path, headers=self.admin, json={
                "name": code, "code": code, "provider_type": "openai_compatible",
                "base_url": "https://example.com",
            }).json()["data"]["id"]

        first, second = provider("first"), provider("second")
        protocol = self.client.post(f"{self.path}/{first}/protocols", headers=self.admin, json={
            "code": "anthropic", "protocol_type": "anthropic",
            "base_url": "https://api.example.com",
        })
        self.assertEqual(protocol.status_code, 201, protocol.text)
        protocol_id = protocol.json()["data"]["id"]
        self.assertEqual(self.client.post(f"{self.path}/{first}/protocols", headers=self.admin, json={
            "code": "anthropic", "protocol_type": "anthropic",
            "base_url": "https://api.example.com",
        }).status_code, 409)
        self.assertEqual(self.client.post(f"{self.path}/{first}/secrets", headers=self.viewer, json={
            "name": "primary", "api_key": "top-secret",
        }).status_code, 403)
        first_secret = self.client.post(f"{self.path}/{first}/secrets", headers=self.admin, json={
            "name": "primary", "api_key": "top-secret",
        }).json()["data"]["id"]
        second_secret = self.client.post(f"{self.path}/{first}/secrets", headers=self.admin, json={
            "name": "backup", "api_key": "backup-secret",
        }).json()["data"]["id"]
        self.assertEqual(len(self.client.get(f"{self.path}/{first}/secrets",
                                             headers=self.admin).json()["data"]), 2)
        self.assertNotIn("top-secret", self.client.get(f"{self.path}/{first}/secrets",
                                                       headers=self.admin).text)
        model = {
            "provider_id": first, "protocol_id": protocol_id, "secret_id": first_secret,
            "access_model_code": "first-chat", "provider_model_name": "chat",
            "model_type": "llm",
        }
        model_path = "/api/admin/v1/access-models"
        self.assertEqual(self.client.post(model_path, json={**model, "provider_id": second},
                                          headers=self.admin).status_code, 422)
        created = self.client.post(model_path, json=model, headers=self.admin)
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(self.client.post(model_path, json={
            **model, "access_model_code": "first-embed", "secret_id": second_secret,
            "provider_model_name": "embed", "model_type": "embedding",
        }, headers=self.admin).status_code, 201)
        self.assertEqual(self.client.get(model_path, params={"provider_id": first},
                                         headers=self.viewer).json()["data"]["total"], 2)
        model_id = created.json()["data"]["id"]
        self.assertEqual(self.client.patch(f"{model_path}/{model_id}", headers=self.admin,
                                           json={"secret_id": None}).json()["data"]["secret_id"], None)
        self.assertEqual(self.client.patch(f"{model_path}/{model_id}", headers=self.admin,
                                           json={"protocol_id": None}).status_code, 422)
        self.assertEqual(self.client.patch(f"{self.path}/{first}/secrets/{first_secret}",
                                           headers=self.admin, json={"status": 0}).status_code, 200)
        self.assertEqual(self.client.patch(f"{model_path}/{model_id}", headers=self.admin,
                                           json={"secret_id": first_secret}).status_code, 422)
        self.assertEqual(self.client.patch(f"{model_path}/{model_id}", headers=self.admin,
                                           json={"status": 0}).status_code, 200)

    def test_create_with_multiple_connections_and_initial_status(self):
        payload = {
            "name": "Multi", "code": "multi", "provider_type": "openai_compatible",
            "base_url": "https://default.example.com", "api_key": "default-key",
            "status": 0,
            "additional_protocols": [
                {"code": "backup", "protocol_type": "anthropic",
                 "base_url": "https://backup.example.com"},
                {"code": "secondary", "protocol_type": "custom",
                 "base_url": "https://secondary.example.com"},
            ],
            "secrets": [
                {"name": "backup", "api_key": "backup-key"},
                {"name": "secondary", "api_key": "secondary-key"},
            ],
        }
        created = self.client.post(self.path, json=payload, headers=self.admin)
        self.assertEqual(created.status_code, 201, created.text)
        item = created.json()["data"]
        self.assertEqual(item["status"], 0)
        listed = self.client.get(self.path, headers=self.admin).json()["data"]["items"][0]
        self.assertEqual((listed["protocol_count"], listed["secret_count"]), (3, 3))
        self.assertEqual((listed["provider_type"], listed["base_url"]),
                         ("openai_compatible", "https://default.example.com/"))
        protocols = self.client.get(f"{self.path}/{item['id']}/protocols",
                                    headers=self.admin).json()["data"]
        secrets = self.client.get(f"{self.path}/{item['id']}/secrets",
                                  headers=self.admin).json()["data"]
        self.assertEqual({p["code"] for p in protocols}, {"default", "backup", "secondary"})
        self.assertEqual({s["name"] for s in secrets}, {"default", "backup", "secondary"})
        self.assertNotIn("backup-key", str(secrets))
        for secret in self.db.query(ProviderSecret).filter_by(provider_id=item["id"]).all():
            expected = f"{secret.name}-key".encode()
            self.assertEqual(Fernet(self.key).decrypt(secret.ciphertext.encode()), expected)

    def test_access_model_type_choices(self):
        provider_id = self.client.post(self.path, headers=self.admin, json={
            "name": "Types", "code": "types", "provider_type": "openai_compatible",
            "base_url": "https://example.com/v1",
        }).json()["data"]["id"]
        protocol_id = self.client.get(
            f"{self.path}/{provider_id}/protocols", headers=self.admin,
        ).json()["data"][0]["id"]
        path = "/api/admin/v1/access-models"
        for model_type in ("llm", "embedding", "rerank", "asr", "tts", "ocr"):
            response = self.client.post(path, headers=self.admin, json={
                "provider_id": provider_id, "protocol_id": protocol_id,
                "access_model_code": f"type-{model_type}", "provider_model_name": "example",
                "model_type": model_type,
            })
            self.assertEqual(response.status_code, 201, response.text)
            self.assertEqual(response.json()["data"]["model_type"], model_type)
        self.assertEqual(self.client.post(path, headers=self.admin, json={
            "provider_id": provider_id, "protocol_id": protocol_id,
            "access_model_code": "invalid-type", "provider_model_name": "example",
            "model_type": "unknown",
        }).status_code, 422)
        self.assertEqual(self.client.patch(f"{path}/1", headers=self.admin, json={
            "model_type": "unknown",
        }).status_code, 422)
        for protocol_type, expected in (("gemini", 201), ("claude", 201), ("custom", 422)):
            protocol = self.client.post(f"{self.path}/{provider_id}/protocols",
                                        headers=self.admin, json={
                "code": protocol_type, "protocol_type": protocol_type,
                "base_url": "https://example.com",
            })
            self.assertEqual(protocol.status_code, 201, protocol.text)
            response = self.client.post(path, headers=self.admin, json={
                "provider_id": provider_id, "protocol_id": protocol.json()["data"]["id"],
                "access_model_code": f"type-{protocol_type}",
                "provider_model_name": "example", "model_type": "llm",
            })
            self.assertEqual(response.status_code, expected, response.text)

    def test_model_specific_connection_settings_and_optional_key(self):
        first = self.client.post(self.path, headers=self.admin, json={
            "name": "First", "code": "first", "provider_type": "gemini",
            "base_url": "https://default.example.com",
        }).json()["data"]["id"]
        second = self.client.post(self.path, headers=self.admin, json={
            "name": "Second", "code": "second", "provider_type": "gemini",
            "base_url": "https://other.example.com",
        }).json()["data"]["id"]
        protocol_id = self.client.get(f"{self.path}/{first}/protocols",
                                      headers=self.admin).json()["data"][0]["id"]
        other_key = self.client.post(f"{self.path}/{second}/secrets", headers=self.admin, json={
            "name": "other", "api_key": "other-secret",
        }).json()["data"]["id"]
        own_key = self.client.post(f"{self.path}/{first}/secrets", headers=self.admin, json={
            "name": "primary", "api_key": "own-secret",
        }).json()["data"]["id"]
        path = "/api/admin/v1/access-models"
        payload = {
            "provider_id": first, "protocol_id": protocol_id, "secret_id": None,
            "access_model_code": "first-llm", "provider_model_name": "gemini-2",
            "model_type": "llm", "base_url": "https://regional.example.com/v1",
            "region": "ap-east", "max_concurrency": 16,
            "context_window": 128000, "timeout_ms": 45000,
        }
        self.assertEqual(self.client.post(path, json=payload, headers=self.viewer).status_code, 403)
        created = self.client.post(path, json=payload, headers=self.admin)
        self.assertEqual(created.status_code, 201, created.text)
        model_id = created.json()["data"]["id"]
        for field in ("base_url", "region", "max_concurrency", "context_window", "timeout_ms"):
            self.assertEqual(created.json()["data"][field], payload[field])
        self.assertIsNone(created.json()["data"]["secret_id"])
        self.assertEqual(self.client.get(f"{path}/{model_id}", headers=self.viewer
                                         ).json()["data"]["base_url"], payload["base_url"])
        self.assertEqual(self.client.get(path, headers=self.viewer
                                         ).json()["data"]["items"][0]["context_window"], 128000)
        updated = self.client.patch(f"{path}/{model_id}", headers=self.admin, json={
            "base_url": "https://new.example.com", "region": "",
            "max_concurrency": None, "context_window": 64000,
            "timeout_ms": None, "secret_id": own_key,
        })
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["data"]["base_url"], "https://new.example.com/")
        self.assertIsNone(updated.json()["data"]["region"])
        self.assertIsNone(updated.json()["data"]["max_concurrency"])
        self.assertEqual(updated.json()["data"]["secret_id"], own_key)
        for change in (
            {"base_url": "file:///etc/passwd"},
            {"max_concurrency": 0}, {"context_window": -1},
            {"timeout_ms": 600001}, {"secret_id": other_key},
        ):
            self.assertEqual(self.client.patch(f"{path}/{model_id}", headers=self.admin,
                                               json=change).status_code, 422)
        for change in (
            {"base_url": "not-a-url"}, {"max_concurrency": 0},
            {"context_window": 2147483648}, {"timeout_ms": -1},
            {"secret_id": other_key},
        ):
            self.assertEqual(self.client.post(path, headers=self.admin, json={
                **payload, "access_model_code": "invalid", **change,
            }).status_code, 422)
        legacy = self.client.post(path, headers=self.admin, json={
            **payload, "access_model_code": "legacy", "base_url": "https://default.example.com",
        })
        self.assertEqual(legacy.status_code, 201, legacy.text)
        regional_protocol = self.client.post(f"{self.path}/{first}/protocols",
                                             headers=self.admin, json={
            "code": "regional", "protocol_type": "gemini",
            "base_url": "https://protocol-only.example.com",
        }).json()["data"]["id"]
        no_url = self.client.post(path, headers=self.admin, json={
            "provider_id": first, "protocol_id": regional_protocol,
            "access_model_code": "implicit", "provider_model_name": "gemini-2",
            "model_type": "llm",
        })
        self.assertEqual(no_url.status_code, 201, no_url.text)
        inherited_id = no_url.json()["data"]["id"]
        self.assertIsNone(no_url.json()["data"]["base_url"])
        self.assertEqual(no_url.json()["data"]["effective_base_url"],
                         "https://default.example.com/")
        cleared = self.client.patch(f"{path}/{model_id}", headers=self.admin, json={
            "base_url": "",
        })
        self.assertEqual(cleared.status_code, 200, cleared.text)
        self.assertIsNone(cleared.json()["data"]["base_url"])
        self.assertEqual(cleared.json()["data"]["effective_base_url"],
                         "https://default.example.com/")
        self.db.get(Provider, first).base_url = "https://changed.example.com/v2"
        self.db.commit()
        self.assertEqual(self.client.get(f"{path}/{inherited_id}", headers=self.viewer
                                         ).json()["data"]["effective_base_url"],
                         "https://changed.example.com/v2")
        self.assertEqual(self.client.get(path, headers=self.viewer
                                         ).json()["data"]["items"][0]["effective_base_url"],
                         "https://changed.example.com/v2")
        self.assertEqual(self.client.get(f"{path}/{legacy.json()['data']['id']}",
                                         headers=self.viewer).json()["data"]["effective_base_url"],
                         "https://default.example.com/")

    def test_create_rejects_duplicate_connections_without_partial_records(self):
        payload = {
            "name": "Duplicate", "code": "duplicate", "provider_type": "custom",
            "base_url": "https://default.example.com", "api_key": "default-key",
            "additional_protocols": [
                {"code": "default", "protocol_type": "custom",
                 "base_url": "https://another.example.com"},
            ],
        }
        self.assertEqual(self.client.post(self.path, json=payload,
                                          headers=self.admin).status_code, 422)
        payload["additional_protocols"][0]["code"] = "backup"
        payload["secrets"] = [{"name": "default", "api_key": "other-key"}]
        self.assertEqual(self.client.post(self.path, json=payload,
                                          headers=self.admin).status_code, 422)
        self.assertEqual(self.client.get(self.path, headers=self.admin).json()["data"]["total"], 0)

    def test_missing_encryption_key_rejects_secret(self):
        with patch("app.modules.provider.router.get_settings",
                   return_value=SimpleNamespace(provider_encryption_key="")):
            response = self.client.post(self.path, headers=self.admin, json={
                "name": "Example", "code": "example", "provider_type": "custom",
                "base_url": "https://example.com", "api_key": "secret",
            })
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.client.get(self.path, headers=self.admin).json()["data"]["total"], 0)


if __name__ == "__main__":
    unittest.main()
