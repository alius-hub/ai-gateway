import json
import socket
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token
from app.db.base import Base
from app.db.models import AggregatedModel, PlaygroundRecord, Provider, ProviderModel, ProviderProtocol, ProviderSecret, User
from app.db.session import get_db
from app.main import app
from app.modules.model.playground_history import MAX_CAPTURE, capture, mask


@compiles(BigInteger, "sqlite")
def compile_bigint(_type, _compiler, **_kwargs):
    return "INTEGER"


@compiles(JSONB, "sqlite")
def compile_jsonb(_type, _compiler, **_kwargs):
    return "JSON"


class PlaygroundTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine, tables=[
            User.__table__, Provider.__table__, ProviderProtocol.__table__,
            ProviderSecret.__table__, ProviderModel.__table__, AggregatedModel.__table__,
            PlaygroundRecord.__table__,
        ])
        self.db = Session(self.engine)
        self.key = Fernet.generate_key().decode()
        self.db.add_all([
            User(id=1, username="admin", email="admin@example.com", password_hash="hash",
                 is_platform_admin=1),
            User(id=2, username="viewer", email="viewer@example.com", password_hash="hash"),
            Provider(id=1, name="Test", code="test", provider_type="openai",
                     base_url="https://example.com/v1", status=1),
            ProviderSecret(id=1, provider_id=1, name="default", status=1,
                           ciphertext=Fernet(self.key).encrypt(b"test-key").decode()),
        ])
        for index, protocol in enumerate(("openai", "anthropic", "gemini"), start=1):
            self.db.add(ProviderProtocol(
                id=index, provider_id=1, code=protocol, protocol_type=protocol,
                base_url="https://example.com/v1" if index != 3 else "https://example.com/v1beta",
                status=1,
            ))
            self.db.add(ProviderModel(
                id=index, provider_id=1, protocol_id=index, secret_id=1,
                access_model_code=f"model-{index}", provider_model_name=f"upstream-{index}",
                model_type="llm", status=1, currency="USD",
            ))
        self.db.add(AggregatedModel(
            id=1, aggregate_model_code="agg", public_model_name="agg", model_type="llm",
            default_routing_strategy="single", routing_model_ids=[1], status=1,
        ))
        self.db.commit()
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.admin = {"Authorization": f"Bearer {create_access_token('1')}"}
        self.viewer = {"Authorization": f"Bearer {create_access_token('2')}"}
        self.url = "/api/admin/v1/playground/chat"
        self.config = patch(
            "app.modules.model.playground.get_settings",
            return_value=SimpleNamespace(provider_encryption_key=self.key),
        )
        self.config.start()

    def tearDown(self):
        self.config.stop()
        app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()

    def payload(self, model_id=1, source="access"):
        return {
            "source": source, "model_id": model_id, "system_prompt": "Be brief",
            "messages": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"},
                {"role": "user", "content": "again"},
            ],
            "temperature": 0.5, "top_p": 0.9, "max_tokens": 64, "stop": ["END"],
        }

    def test_protocols_and_aggregate(self):
        original_client = httpx.AsyncClient
        seen = []

        def handler(request):
            seen.append(request)
            self.assertNotIn("test-key", str(request.url))
            if "/chat/completions" in str(request.url):
                self.assertEqual(request.headers["authorization"], "Bearer test-key")
                self.assertEqual(request.read().decode().count('"role"'), 4)
                data = {"choices": [{"message": {"content": "openai reply"}}],
                        "usage": {"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10}}
            elif "/messages" in str(request.url):
                self.assertEqual(request.headers["x-api-key"], "test-key")
                self.assertIn(b"stop_sequences", request.read())
                data = {"content": [{"type": "text", "text": "claude reply"}],
                        "usage": {"input_tokens": 8, "output_tokens": 2}}
            else:
                self.assertEqual(request.headers["x-goog-api-key"], "test-key")
                self.assertIn(b"systemInstruction", request.read())
                data = {"candidates": [{"content": {"parts": [{"text": "gemini reply"}]}}],
                        "usageMetadata": {"promptTokenCount": 8, "candidatesTokenCount": 2,
                                          "totalTokenCount": 10}}
            return httpx.Response(200, json=data)

        with patch("app.modules.model.playground.httpx.AsyncClient",
                   side_effect=lambda **kwargs: original_client(
                       transport=httpx.MockTransport(handler), **kwargs)):
            for model_id, expected in ((1, "openai reply"), (2, "claude reply"),
                                       (3, "gemini reply")):
                response = self.client.post(self.url, json=self.payload(model_id), headers=self.admin)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["data"]["content"], expected)
                self.assertEqual(response.json()["data"]["usage"]["total_tokens"], 10)
                self.assertNotIn("test-key", response.text)
            response = self.client.post(self.url, json=self.payload(1, "aggregate"),
                                        headers=self.admin)
            self.assertEqual(response.json()["data"]["access_model_code"], "model-1")
        self.assertEqual(len(seen), 4)
        records = self.client.get("/api/admin/v1/playground/history", headers=self.admin).json()["data"]
        self.assertEqual(records["total"], 4)
        detail = self.client.get(
            f"/api/admin/v1/playground/history/{records['items'][0]['id']}",
            headers=self.admin,
        ).json()["data"]
        self.assertEqual(detail["request_body"]["messages"][0]["role"], "system")
        self.assertIn('"choices"', detail["response_body"])
        self.assertEqual(detail["parsed_content"], "openai reply")
        self.assertEqual(
            {key.lower(): value for key, value in detail["request_headers"].items()}["authorization"],
            "[REDACTED]",
        )

    def test_validation_and_authorization(self):
        self.assertEqual(self.client.post(self.url, json=self.payload(), headers=self.viewer).status_code, 403)
        invalid = self.payload()
        invalid["messages"][-1]["role"] = "assistant"
        self.assertEqual(self.client.post(self.url, json=invalid, headers=self.admin).status_code, 422)
        invalid = self.payload()
        invalid["temperature"] = 3
        self.assertEqual(self.client.post(self.url, json=invalid, headers=self.admin).status_code, 422)
        self.db.get(ProviderModel, 1).status = 0
        self.db.commit()
        self.assertEqual(self.client.post(self.url, json=self.payload(), headers=self.admin).status_code, 422)

    def test_model_list_filters_provider_name_and_aggregate(self):
        path = "/api/admin/v1/access-models"
        filters = json.dumps({"mode": "and", "conditions": [
            {"field": "provider_name", "operator": "contains", "value": "Test"},
            {"field": "id", "operator": "eq", "value": "1"},
        ]})
        result = self.client.get(path, headers=self.admin,
                                 params={"filters": filters, "page_size": 1})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["data"]["total"], 1)
        self.assertEqual(result.json()["data"]["items"][0]["id"], 1)
        aggregate = self.client.get("/api/admin/v1/aggregate-models", headers=self.admin,
                                    params={"filters": json.dumps({"mode": "and", "conditions": [
                                        {"field": "aggregate_model_code", "operator": "eq",
                                         "value": "agg"},
                                    ]})})
        self.assertEqual(aggregate.status_code, 200, aggregate.text)
        self.assertEqual(aggregate.json()["data"]["total"], 1)

    def test_custom_connection_and_private_address_rejection(self):
        original_client = httpx.AsyncClient
        payload = self.payload()
        payload.update({
            "source": "custom", "model_id": None, "custom_protocol": "openai_compatible",
            "custom_base_url": "https://api.example.com/v1",
            "custom_model_name": "temporary-model", "custom_api_key": "temporary-secret",
        })
        self.assertEqual(self.client.post(self.url, json=payload, headers=self.viewer).status_code, 403)
        requests = []

        def handler(request):
            requests.append(request)
            self.assertEqual(str(request.url), "https://api.example.com/v1/chat/completions")
            self.assertEqual(request.headers["authorization"], "Bearer temporary-secret")
            self.assertIn(b"temporary-model", request.read())
            return httpx.Response(200, json={
                "choices": [{"message": {"content": "custom reply"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
            })

        with patch("app.modules.model.playground.socket.getaddrinfo",
                   return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                                  ("93.184.215.14", 443))]), \
                patch("app.modules.model.playground.httpx.AsyncClient",
                      side_effect=lambda **kwargs: original_client(
                          transport=httpx.MockTransport(handler), **kwargs)):
            response = self.client.post(self.url, json=payload, headers=self.admin)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["data"]["access_model_code"], "temporary-model")
        self.assertEqual(response.json()["data"]["content"], "custom reply")
        self.assertNotIn("temporary-secret", response.text)
        self.assertEqual(len(requests), 1)

        invalid = dict(payload, model_id=1)
        self.assertEqual(self.client.post(self.url, json=invalid, headers=self.admin).status_code, 422)
        invalid = dict(payload, custom_base_url="http://127.0.0.1:8001")
        self.assertEqual(self.client.post(self.url, json=invalid, headers=self.admin).status_code, 422)
        invalid = dict(payload, custom_base_url="https://localhost/v1")
        self.assertEqual(self.client.post(self.url, json=invalid, headers=self.admin).status_code, 422)
        with patch("app.modules.model.playground.socket.getaddrinfo",
                   return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                                  ("10.0.0.1", 443))]):
            invalid = dict(payload, custom_base_url="https://private.example.com/v1")
            self.assertEqual(self.client.post(self.url, json=invalid, headers=self.admin).status_code, 422)
        invalid = self.payload()
        invalid["custom_api_key"] = "stolen"
        self.assertEqual(self.client.post(self.url, json=invalid, headers=self.admin).status_code, 422)

    def test_raw_body_headers_and_stream_frames(self):
        original_client = httpx.AsyncClient
        captured = []

        def handler(request):
            captured.append(request)
            body = request.read().decode()
            if "streamGenerateContent" in str(request.url):
                self.assertIn("alt=sse", str(request.url))
                self.assertNotIn('"stream"', body)
            else:
                self.assertIn('"stream":true', body)
                self.assertEqual(request.headers["x-debug-label"], "manual")
                self.assertIn('"temperature":0.25', body)
                self.assertIn('"model":"manual-model"', body)
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=b'data: {"text":"first"}\n\ndata: {"text":"second"}\n\n')

        raw = {
            "source": "access", "model_id": 1,
            "headers": {"x-debug-label": "manual"},
            "body": {"model": "manual-model", "messages": [{"role": "user", "content": "hi"}],
                     "temperature": 0.25, "stream": False},
            "stream": True,
        }
        with patch("app.modules.model.playground.httpx.AsyncClient",
                   side_effect=lambda **kwargs: original_client(
                       transport=httpx.MockTransport(handler), **kwargs)):
            response = self.client.post("/api/admin/v1/playground/raw", json=raw,
                                        headers=self.admin)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.headers["content-type"].split(";")[0], "text/event-stream")
            self.assertIn('data: {"text":"first"}', response.text)
            self.assertNotIn("test-key", response.text)
            gemini = self.payload(3)
            response = self.client.post("/api/admin/v1/playground/chat/stream", json=gemini,
                                        headers=self.admin)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIn('data: {"text":"second"}', response.text)
        self.assertEqual(len(captured), 2)
        raw["headers"] = {"Host": "localhost"}
        self.assertEqual(self.client.post("/api/admin/v1/playground/raw", json=raw,
                                          headers=self.admin).status_code, 422)
        raw["headers"] = {}
        self.assertEqual(self.client.post("/api/admin/v1/playground/raw", json=raw,
                                          headers=self.viewer).status_code, 403)

    def test_raw_upstream_error_is_visible(self):
        original_client = httpx.AsyncClient
        raw = {"source": "access", "model_id": 1, "body": {"model": "upstream-1"},
               "stream": False}
        with patch("app.modules.model.playground.httpx.AsyncClient",
                   side_effect=lambda **kwargs: original_client(
                       transport=httpx.MockTransport(
                           lambda _request: httpx.Response(429, text='{"error":"rate limit"}')),
                       **kwargs)):
            response = self.client.post("/api/admin/v1/playground/raw", json=raw,
                                        headers=self.admin)
        self.assertEqual(response.status_code, 429)
        self.assertIn("rate limit", response.text)

    def test_history_contains_actual_request_and_response_without_keys(self):
        original_client = httpx.AsyncClient
        payload = {"source": "access", "model_id": 1, "stream": True,
                   "body": {"model": "manual", "messages": [
                       {"role": "user", "content": "hello"}], "max_tokens": 123},
                   "headers": {"X-Debug": "visible", "Authorization": "Bearer override-key"}}

        def handler(_request):
            return httpx.Response(200, content=(
                b'data: {"text":"first"}\n\ndata: {"text":"Bearer override-key"}\n\n'
                b'data: [DONE]\n\n'))

        with patch("app.modules.model.playground.httpx.AsyncClient",
                   side_effect=lambda **kwargs: original_client(
                       transport=httpx.MockTransport(handler), **kwargs)):
            self.assertEqual(self.client.post("/api/admin/v1/playground/raw",
                                              json=payload, headers=self.admin).status_code, 200)
        path = "/api/admin/v1/playground/history"
        self.assertEqual(self.client.get(path, headers=self.viewer).status_code, 403)
        listed = self.client.get(path, headers=self.admin).json()["data"]
        self.assertEqual(listed["total"], 1)
        record_id = listed["items"][0]["id"]
        self.assertTrue(listed["items"][0]["stream"])
        self.assertNotIn("request_body", listed["items"][0])
        detail = self.client.get(f"{path}/{record_id}", headers=self.admin).json()["data"]
        self.assertEqual(detail["request_body"]["max_tokens"], 123)
        self.assertTrue(detail["request_body"]["stream"])
        self.assertEqual(detail["request_headers"]["x-debug"], "visible")
        self.assertEqual(detail["request_headers"]["authorization"], "[REDACTED]")
        self.assertIn('data: {"text":"first"}', detail["response_body"])
        self.assertEqual(detail["http_status"], 200)
        self.assertNotIn("override-key", str(detail))
        self.assertNotIn("test-key", str(detail))
        self.db.get(User, 2).is_platform_admin = 1
        self.db.commit()
        self.assertEqual(self.client.get(path, headers=self.viewer).json()["data"]["total"], 0)
        self.assertEqual(self.client.get(f"{path}/{record_id}", headers=self.viewer).status_code, 404)
        self.assertEqual(self.client.delete(f"{path}/{record_id}", headers=self.viewer).status_code, 404)
        self.assertEqual(self.client.delete(f"{path}/{record_id}", headers=self.admin).status_code, 200)
        self.assertEqual(self.client.get(path, headers=self.admin).json()["data"]["total"], 0)
        self.assertEqual(self.client.get(f"{path}/{record_id}", headers=self.admin).status_code, 404)
        self.assertEqual(self.client.delete(f"{path}/{record_id}", headers=self.admin).status_code, 404)

    def test_stream_history_parsing_and_pending_delete(self):
        from app.modules.model.playground_history import parsed_content

        record = PlaygroundRecord(user_id=1, mode="conversation", source="access",
                                  model_code="model-1", protocol="openai", stream=True,
                                  request_url="https://example.com", request_headers={}, request_body={},
                                  http_status=200, truncated=False, response_body=(
                                      'data: {"choices":[{"delta":{"content":"hello "}}]}\n\n'
                                      'data: {"choices":[{"delta":{"content":"world"}}]}\n\n'
                                      "data: [DONE]\n\n"))
        self.db.add(record)
        self.db.commit()
        self.assertEqual(parsed_content(record), "hello world")
        record.protocol = "anthropic"
        record.response_body = ('event: content_block_delta\n'
                                'data: {"delta":{"type":"text_delta","text":"Claude"}}\n\n')
        self.assertEqual(parsed_content(record), "Claude")
        record.protocol = "gemini"
        record.response_body = (
            'data: {"candidates":[{"content":{"parts":[{"text":"hello"}]}}]}\n\n'
            'data: {"candidates":[{"content":{"parts":[{"text":"hello world"}]}}]}\n\n')
        self.assertEqual(parsed_content(record), "hello world")
        record.response_body += 'data: {"candidates":'
        self.assertEqual(parsed_content(record), "hello world")
        record.http_status = None
        self.db.commit()
        self.assertEqual(self.client.delete(f"/api/admin/v1/playground/history/{record.id}",
                                            headers=self.admin).status_code, 409)

    def test_history_redaction_and_capture_limit(self):
        safe = mask({"max_tokens": 512, "messages": [{"content": "key-value"}],
                     "nested": {"api_key": "key-value"}, "x-debug": "key-value"}, "key-value")
        self.assertEqual(safe["max_tokens"], 512)
        self.assertEqual(safe["messages"][0]["content"], "[REDACTED]")
        self.assertEqual(safe["nested"]["api_key"], "[REDACTED]")
        text, truncated = capture("x" * (MAX_CAPTURE + 10), None)
        self.assertEqual(len(text), MAX_CAPTURE)
        self.assertTrue(truncated)
