import copy
import unittest

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token
from app.db.base import Base
from app.db.models import AggregatedModel, Provider, ProviderModel, RoutingWorkflow, User
from app.db.session import get_db
from app.main import app
from app.modules.routing.workflow import Definition, validate_bindings, validate_definition


@compiles(BigInteger, "sqlite")
def bigint_sqlite(_type, _compiler, **_kwargs):
    return "INTEGER"


@compiles(JSONB, "sqlite")
def jsonb_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


class RoutingWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(self.engine, tables=[
            User.__table__, Provider.__table__, ProviderModel.__table__,
            RoutingWorkflow.__table__, AggregatedModel.__table__,
        ])
        self.db = Session(self.engine)
        self.db.add_all([
            User(id=1, username="admin", email="admin@example.com", password_hash="hash", is_platform_admin=1),
            User(id=2, username="viewer", email="viewer@example.com", password_hash="hash"),
            Provider(id=1, name="Example", code="example", provider_type="openai",
                     base_url="https://api.example.com"),
            ProviderModel(id=10, provider_id=1, access_model_code="east", provider_model_name="chat-a",
                          model_type="llm", status=1),
            ProviderModel(id=11, provider_id=1, access_model_code="backup", provider_model_name="chat-b",
                          model_type="llm", status=1),
            ProviderModel(id=12, provider_id=1, access_model_code="embed", provider_model_name="vector",
                          model_type="embedding", status=1),
            ProviderModel(id=13, provider_id=1, access_model_code="embed-backup", provider_model_name="vector-b",
                          model_type="embedding", status=1),
        ])
        self.db.commit()
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.path = "/api/admin/v1/routing/workflows"
        self.admin = {"Authorization": f"Bearer {create_access_token('1')}"}
        self.viewer = {"Authorization": f"Bearer {create_access_token('2')}"}
        self.graph = {
            "nodes": [
                {"id": "start", "type": "start"},
                {"id": "region", "type": "condition", "config": {"field": "region", "value": "cn-east"}},
                {"id": "primary", "type": "select", "config": {"model_id": 10}},
                {"id": "pool", "type": "weighted", "config": {"candidates": [
                    {"model_id": 10, "weight": 70}, {"model_id": 11, "weight": 30},
                ]}},
                {"id": "backup", "type": "select", "config": {"model_id": 11}},
                {"id": "reject", "type": "reject"},
            ],
            "edges": [
                {"source": "start", "label": "next", "target": "region"},
                {"source": "region", "label": "true", "target": "primary"},
                {"source": "region", "label": "false", "target": "pool"},
                {"source": "primary", "label": "unavailable", "target": "backup"},
                {"source": "pool", "label": "unavailable", "target": "backup"},
                {"source": "backup", "label": "unavailable", "target": "reject"},
            ],
        }
        self.payload = {"name": "Regional", "model_type": "llm", "definition": self.graph}

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()

    def seed_workflow(self, definition=None, model_type="llm"):
        item = RoutingWorkflow(name="Historical", model_type=model_type,
                               definition=Definition.model_validate(definition or self.graph).model_dump())
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item.id

    def seed_aggregate(self, workflow_id, code, model_type="llm", bindings=None):
        item = AggregatedModel(
            aggregate_model_code=code, public_model_name=code, model_type=model_type,
            default_routing_strategy="workflow", workflow_id=workflow_id,
            workflow_bindings=bindings, status=1,
        )
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item.id

    def test_read_simulate_fallback_and_bind_historical_workflow(self):
        self.assertEqual(self.client.post(self.path, json=self.payload, headers=self.admin).status_code, 405)
        workflow_id = self.seed_workflow()
        self.assertEqual(self.client.get(self.path, headers=self.viewer).json()["data"]["total"], 1)
        simulate = f"{self.path}/{workflow_id}/simulate"
        result = self.client.post(simulate, json={"region": "cn-east"}, headers=self.viewer)
        self.assertEqual(result.json()["data"]["selected_model_id"], 10)
        self.db.get(ProviderModel, 10).status = 0
        self.db.commit()
        result = self.client.post(simulate, json={"region": "cn-east"}, headers=self.viewer)
        self.assertEqual(result.json()["data"]["selected_model_id"], 11)
        self.assertEqual(result.json()["data"]["trace"][-2]["outcome"], "unavailable")
        aggregate = {
            "aggregate_model_code": "chat-pro", "public_model_name": "chat-pro",
            "model_type": "llm", "workflow_id": workflow_id, "status": 1,
        }
        self.assertEqual(self.client.post("/api/admin/v1/aggregate-models", json=aggregate,
                                          headers=self.admin).status_code, 422)
        aggregate_id = self.seed_aggregate(workflow_id, "chat-pro")
        listed = self.client.get("/api/admin/v1/aggregate-models", headers=self.viewer)
        self.assertEqual(listed.json()["data"]["items"][0]["workflow_id"], workflow_id)
        self.assertEqual(self.client.post(f"/api/admin/v1/aggregate-models/{aggregate_id}/simulate",
                                          json={"region": "cn-east"}, headers=self.viewer).status_code, 200)
        self.assertEqual(self.client.put(f"{self.path}/{workflow_id}", json=self.payload,
                                         headers=self.admin).status_code, 405)
        self.assertEqual(self.client.patch("/api/admin/v1/access-models/11",
                                           json={"model_type": "embedding"}, headers=self.admin).status_code, 409)
        self.assertEqual(self.client.post("/api/admin/v1/aggregate-models", json=aggregate,
                                          headers=self.admin).status_code, 422)
        self.db.get(ProviderModel, 11).status = 0
        self.db.commit()
        self.assertIsNone(self.client.post(simulate, json={"region": "cn-east"},
                                           headers=self.viewer).json()["data"]["selected_model_id"])

    def test_reject_invalid_graphs_and_model_types(self):
        def expect_invalid(graph):
            with self.assertRaises(HTTPException) as context:
                validate_definition(self.db, Definition.model_validate(graph), "llm")
            self.assertEqual(context.exception.status_code, 422)

        cyclic = copy.deepcopy(self.graph)
        cyclic["edges"].append({"source": "backup", "label": "unavailable", "target": "region"})
        # Replace the existing edge so duplicate-outlet validation does not mask cycle detection.
        cyclic["edges"].pop(-2)
        expect_invalid(cyclic)
        dangling = copy.deepcopy(self.graph)
        dangling["edges"] = [edge for edge in dangling["edges"] if edge["label"] != "false"]
        expect_invalid(dangling)
        wrong_type = copy.deepcopy(self.graph)
        wrong_type["nodes"][2]["config"]["model_id"] = 12
        expect_invalid(wrong_type)
        duplicate = copy.deepcopy(self.graph)
        duplicate["nodes"][3]["config"]["candidates"][1]["model_id"] = 10
        expect_invalid(duplicate)
        unreachable = copy.deepcopy(self.graph)
        unreachable["edges"] = [edge for edge in unreachable["edges"] if edge["source"] != "backup"]
        expect_invalid(unreachable)
        workflow_id = self.seed_workflow()
        with self.assertRaises(HTTPException) as context:
            validate_bindings(self.db, Definition.model_validate(self.graph), {}, "embedding")
        self.assertEqual(context.exception.status_code, 422)
        self.assertIsNotNone(self.db.get(RoutingWorkflow, workflow_id))

    def test_generic_workflow_reused_across_model_types_and_terminal_routing(self):
        definition = {
            "nodes": [
                {"id": "start", "type": "start"},
                {"id": "region", "type": "condition", "config": {"field": "region", "value": "cn-east"}},
                {"id": "pool", "type": "round_robin", "config": {"slot": "main"}},
                {"id": "latency", "type": "least_latency", "config": {"slot": "fast"}},
                {"id": "single", "type": "single", "config": {"slot": "fallback"}},
            ],
            "edges": [
                {"source": "start", "label": "next", "target": "region"},
                {"source": "region", "label": "true", "target": "pool"},
                {"source": "region", "label": "false", "target": "latency"},
                {"source": "latency", "label": "unavailable", "target": "single"},
            ],
        }
        workflow_id = self.seed_workflow(definition, model_type=None)
        detail = self.client.get(f"{self.path}/{workflow_id}", headers=self.viewer)
        self.assertIsNone(detail.json()["data"]["model_type"])
        direct = self.client.post(f"{self.path}/{workflow_id}/simulate", json={
            "region": "cn-west", "latencies": {"10": 50, "11": 100},
            "bindings": {"main": [10, 11], "fast": [10, 11], "fallback": [11]},
        }, headers=self.viewer)
        self.assertEqual(direct.status_code, 200, direct.text)
        self.assertEqual(direct.json()["data"]["selected_model_id"], 10)
        aggregate_path = "/api/admin/v1/aggregate-models"
        llm = {
            "aggregate_model_code": "generic-chat", "public_model_name": "generic-chat",
            "model_type": "llm", "workflow_id": workflow_id, "status": 1,
            "workflow_bindings": {"main": [10, 11], "fast": [10, 11], "fallback": [11]},
        }
        self.assertEqual(self.client.post(aggregate_path, json=llm, headers=self.admin).status_code, 422)
        invalid = copy.deepcopy(llm)
        invalid["workflow_bindings"]["fast"] = [10, 12]
        with self.assertRaises(HTTPException):
            validate_bindings(self.db, Definition.model_validate(definition), invalid["workflow_bindings"], "llm")
        invalid["workflow_bindings"]["fast"] = [10, 10]
        with self.assertRaises(HTTPException):
            validate_bindings(self.db, Definition.model_validate(definition), invalid["workflow_bindings"], "llm")
        invalid["workflow_bindings"]["fast"] = [10, 11]
        invalid["workflow_bindings"]["main"] = [10]
        with self.assertRaises(HTTPException):
            validate_bindings(self.db, Definition.model_validate(definition), invalid["workflow_bindings"], "llm")
        invalid["workflow_bindings"]["main"] = [10, 11]
        invalid["workflow_bindings"]["extra"] = [10]
        with self.assertRaises(HTTPException):
            validate_bindings(self.db, Definition.model_validate(definition), invalid["workflow_bindings"], "llm")
        chat_id = self.seed_aggregate(workflow_id, "generic-chat", bindings=llm["workflow_bindings"])
        embedding_id = self.seed_aggregate(workflow_id, "generic-embed", model_type="embedding",
                                           bindings={"main": [12, 13], "fast": [12, 13], "fallback": [13]})
        simulate_chat = f"{aggregate_path}/{chat_id}/simulate"
        east = self.client.post(simulate_chat, json={"region": "cn-east", "round_robin_index": 0},
                                headers=self.viewer)
        self.assertEqual(east.json()["data"]["selected_model_id"], 10)
        east = self.client.post(simulate_chat, json={"region": "cn-east", "round_robin_index": 1},
                                headers=self.viewer)
        self.assertEqual(east.json()["data"]["selected_model_id"], 11)
        west = self.client.post(simulate_chat, json={"region": "cn-west", "latencies": {"10": 95, "11": 32}},
                                headers=self.viewer)
        self.assertEqual(west.json()["data"]["selected_model_id"], 11)
        no_metrics = self.client.post(simulate_chat, json={"region": "cn-west"}, headers=self.viewer)
        self.assertEqual(no_metrics.json()["data"]["selected_model_id"], 11)
        self.assertEqual(no_metrics.json()["data"]["trace"][-2]["outcome"], "unavailable")
        self.assertEqual(self.client.post(simulate_chat, json={"latencies": {"10": -1}},
                                          headers=self.viewer).status_code, 422)
        embed = self.client.post(f"{aggregate_path}/{embedding_id}/simulate",
                                 json={"region": "cn-west", "latencies": {"12": 10, "13": 20}},
                                 headers=self.viewer)
        self.assertEqual(embed.json()["data"]["selected_model_id"], 12)
        self.assertEqual(self.client.put(f"{self.path}/{workflow_id}", json={
            "name": "Changed", "definition": definition,
        }, headers=self.admin).status_code, 405)
        self.assertEqual(self.client.patch("/api/admin/v1/access-models/12", json={
            "model_type": "llm",
        }, headers=self.admin).status_code, 409)

    def test_builtin_strategies_and_direct_aggregate_models(self):
        strategy_list = self.client.get("/api/admin/v1/routing/strategies", headers=self.viewer)
        self.assertEqual([item["code"] for item in strategy_list.json()["data"]["items"]],
                         ["single", "round_robin", "least_latency"])
        path = "/api/admin/v1/aggregate-models"
        base = {"aggregate_model_code": "builtin-chat", "public_model_name": "builtin-chat",
                "model_type": "llm", "default_routing_strategy": "single",
                "routing_model_ids": [10], "status": 1}
        self.assertEqual(self.client.post(path, json=base, headers=self.viewer).status_code, 403)
        invalid = {**base, "routing_model_ids": [12]}
        self.assertEqual(self.client.post(path, json=invalid, headers=self.admin).status_code, 422)
        invalid = {**base, "routing_model_ids": [10, 11]}
        self.assertEqual(self.client.post(path, json=invalid, headers=self.admin).status_code, 422)
        invalid = {**base, "default_routing_strategy": "round_robin", "routing_model_ids": [10, 10]}
        self.assertEqual(self.client.post(path, json=invalid, headers=self.admin).status_code, 422)
        invalid = {**base, "default_routing_strategy": "round_robin", "routing_model_ids": [10]}
        self.assertEqual(self.client.post(path, json=invalid, headers=self.admin).status_code, 422)
        single = self.client.post(path, json=base, headers=self.admin)
        self.assertEqual(single.status_code, 201, single.text)
        self.assertIsNone(single.json()["data"]["workflow_id"])
        self.assertEqual(single.json()["data"]["routing_model_ids"], [10])
        single_id = single.json()["data"]["id"]
        response = self.client.post(f"{path}/{single_id}/simulate", json={}, headers=self.viewer)
        self.assertEqual(response.json()["data"]["selected_model_id"], 10)
        self.assertEqual(self.client.patch("/api/admin/v1/access-models/10", json={
            "model_type": "embedding",
        }, headers=self.admin).status_code, 409)

        round_robin = {**base, "aggregate_model_code": "builtin-round",
                       "public_model_name": "builtin-round",
                       "default_routing_strategy": "round_robin", "routing_model_ids": [10, 11]}
        created = self.client.post(path, json=round_robin, headers=self.admin)
        self.assertEqual(created.status_code, 201, created.text)
        simulate = f"{path}/{created.json()['data']['id']}/simulate"
        self.assertEqual(self.client.post(simulate, json={"round_robin_index": 0},
                                          headers=self.viewer).json()["data"]["selected_model_id"], 10)
        self.assertEqual(self.client.post(simulate, json={"round_robin_index": 1},
                                          headers=self.viewer).json()["data"]["selected_model_id"], 11)
        latency = {**base, "aggregate_model_code": "builtin-latency",
                   "public_model_name": "builtin-latency",
                   "default_routing_strategy": "least_latency", "routing_model_ids": [10, 11]}
        created = self.client.post(path, json=latency, headers=self.admin)
        self.assertEqual(created.status_code, 201, created.text)
        simulate = f"{path}/{created.json()['data']['id']}/simulate"
        self.assertIsNone(self.client.post(simulate, json={},
                                           headers=self.viewer).json()["data"]["selected_model_id"])
        self.assertEqual(self.client.post(simulate, json={"latencies": {"10": 90, "11": 30}},
                                          headers=self.viewer).json()["data"]["selected_model_id"], 11)
        self.assertEqual(self.client.post(simulate, json={"latencies": {"10": -1}},
                                          headers=self.viewer).status_code, 422)
        self.db.get(ProviderModel, 11).status = 0
        self.db.commit()
        self.assertEqual(self.client.post(simulate, json={"latencies": {"10": 90, "11": 30}},
                                          headers=self.viewer).json()["data"]["selected_model_id"], 10)
        self.assertEqual(self.client.post(f"{path}/{single_id}/simulate", json={},
                                          headers=self.viewer).json()["data"]["selected_model_id"], 10)
        embedding = {**base, "aggregate_model_code": "builtin-embed", "public_model_name": "builtin-embed",
                     "model_type": "embedding", "routing_model_ids": [12]}
        self.assertEqual(self.client.post(path, json=embedding, headers=self.admin).status_code, 201)

    def test_switch_legacy_aggregate_without_deleting_workflow(self):
        workflow_id = self.seed_workflow()
        path = "/api/admin/v1/aggregate-models"
        legacy = {"aggregate_model_code": "legacy-model", "public_model_name": "legacy-model",
                  "model_type": "llm", "workflow_id": workflow_id, "status": 1}
        self.assertEqual(self.client.post(path, json=legacy, headers=self.admin).status_code, 422)
        aggregate_id = self.seed_aggregate(workflow_id, "legacy-model")
        converted = {"aggregate_model_code": "legacy-model", "public_model_name": "legacy-model",
                     "model_type": "llm", "status": 1, "default_routing_strategy": "round_robin",
                     "routing_model_ids": [10, 11]}
        updated = self.client.put(f"{path}/{aggregate_id}", json=converted, headers=self.admin)
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertIsNone(updated.json()["data"]["workflow_id"])
        self.assertEqual(updated.json()["data"]["routing_model_ids"], [10, 11])
        self.assertIsNotNone(self.db.get(RoutingWorkflow, workflow_id))

    def test_optional_fallback_from_catalog_and_extended_model_names(self):
        path = "/api/admin/v1/aggregate-models"
        base = {
            "aggregate_model_code": "聚合.Chat_Pro-01", "public_model_name": "对外.Chat_Pro-01",
            "model_type": "llm", "default_routing_strategy": "single",
            "routing_model_ids": [10], "fallback_model_id": 11, "status": 1,
        }
        for field, value in (
            ("aggregate_model_code", "bad/name"), ("aggregate_model_code", "中文 空格"),
            ("public_model_name", "bad/name"), ("public_model_name", "中文 空格"),
        ):
            response = self.client.post(path, json={**base, field: value}, headers=self.admin)
            self.assertEqual(response.status_code, 422, response.text)
        for fallback_id in (12, 999, 0, -1):
            response = self.client.post(path, json={**base, "fallback_model_id": fallback_id},
                                        headers=self.admin)
            self.assertEqual(response.status_code, 422, response.text)
        created = self.client.post(path, json=base, headers=self.admin)
        self.assertEqual(created.status_code, 201, created.text)
        aggregate_id = created.json()["data"]["id"]
        self.assertEqual(created.json()["data"]["fallback_model_id"], 11)
        listed = self.client.get(path, headers=self.viewer).json()["data"]["items"]
        self.assertEqual(listed[0]["fallback_model_id"], 11)
        self.assertEqual(self.client.patch("/api/admin/v1/access-models/11", json={
            "model_type": "embedding",
        }, headers=self.admin).status_code, 409)
        self.db.get(ProviderModel, 10).status = 0
        self.db.commit()
        simulation = self.client.post(f"{path}/{aggregate_id}/simulate", json={}, headers=self.viewer)
        self.assertEqual(simulation.json()["data"]["selected_model_id"], 11)
        self.assertEqual(simulation.json()["data"]["trace"][-1]["strategy"], "fallback")
        self.assertEqual(self.client.put(f"{path}/{aggregate_id}", json={
            **base, "status": 0,
        }, headers=self.admin).json()["data"]["fallback_model_id"], 11)
        self.db.get(ProviderModel, 11).status = 0
        self.db.commit()
        self.assertIsNone(self.client.post(f"{path}/{aggregate_id}/simulate", json={},
                                           headers=self.viewer).json()["data"]["selected_model_id"])
        self.assertEqual(self.client.put(f"{path}/{aggregate_id}", json=base,
                                         headers=self.admin).status_code, 422)
        cleared = self.client.put(f"{path}/{aggregate_id}", json={
            **base, "fallback_model_id": None, "status": 0,
        }, headers=self.admin)
        self.assertEqual(cleared.status_code, 200, cleared.text)
        self.assertIsNone(cleared.json()["data"]["fallback_model_id"])

    def test_optional_fallback_from_aggregate_candidates(self):
        path = "/api/admin/v1/aggregate-models"
        payload = {
            "aggregate_model_code": "Latency.聚合", "public_model_name": "Latency.聚合",
            "model_type": "llm", "default_routing_strategy": "least_latency",
            "routing_model_ids": [10, 11], "fallback_model_id": 10, "status": 1,
        }
        created = self.client.post(path, json=payload, headers=self.admin)
        self.assertEqual(created.status_code, 201, created.text)
        simulation = self.client.post(f"{path}/{created.json()['data']['id']}/simulate",
                                      json={}, headers=self.viewer)
        self.assertEqual(simulation.json()["data"]["selected_model_id"], 10)
        self.assertEqual(simulation.json()["data"]["trace"][-1]["strategy"], "fallback")
        measured = self.client.post(f"{path}/{created.json()['data']['id']}/simulate",
                                    json={"latencies": {"11": 12}}, headers=self.viewer)
        self.assertEqual(measured.json()["data"]["selected_model_id"], 11)
        self.assertEqual(len(measured.json()["data"]["trace"]), 1)
