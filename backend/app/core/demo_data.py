from __future__ import annotations

from copy import deepcopy
from decimal import Decimal


USERS = [
    {
        "id": 1,
        "username": "admin",
        "email": "admin@ai-gateway.local",
        "password_hash": "sha256$ad89b64d66caa8e30e5d5ce4a9763f4ecc205814c412175f3e2c50027471426d",
        "nickname": "平台管理员",
        "avatar_url": None,
        "status": 1,
    }
]

ORGANIZATIONS = [
    {"id": 1, "name": "默认组织", "code": "default-org", "status": 1, "description": "平台默认租户"},
    {"id": 2, "name": "演示组织", "code": "demo-org", "status": 1, "description": "用于联调和演示"},
]

PROJECTS = [
    {
        "id": 1,
        "organization_id": 1,
        "name": "AI Gateway MVP",
        "code": "gateway-mvp",
        "environment": "dev",
        "status": 1,
        "description": "平台核心控制台",
    },
    {
        "id": 2,
        "organization_id": 2,
        "name": "企业知识助手",
        "code": "enterprise-kb",
        "environment": "uat",
        "status": 1,
        "description": "给业务团队演示的测试项目",
    },
]

API_KEYS = [
    {
        "id": 1,
        "organization_id": 1,
        "project_id": 1,
        "user_id": None,
        "scope_type": "project",
        "name": "gateway-mvp-key",
        "key_prefix": "agw_sk_mvp",
        "key_hash": "demo-key-hash-1",
        "status": 1,
        "allowed_models": ["chat-pro", "text-embedding-pro"],
    },
    {
        "id": 2,
        "organization_id": 2,
        "project_id": 2,
        "user_id": None,
        "scope_type": "project",
        "name": "enterprise-kb-key",
        "key_prefix": "agw_sk_kb",
        "key_hash": "demo-key-hash-2",
        "status": 1,
        "allowed_models": ["chat-pro"],
    },
]

PROVIDERS = [
    {
        "id": 1,
        "organization_id": None,
        "name": "OpenAI",
        "code": "openai",
        "provider_type": "openai_compatible",
        "base_url": "https://api.openai.com/v1",
        "status": 1,
        "health_status": "healthy",
    },
    {
        "id": 2,
        "organization_id": None,
        "name": "DeepSeek",
        "code": "deepseek",
        "provider_type": "openai_compatible",
        "base_url": "https://api.deepseek.com",
        "status": 1,
        "health_status": "healthy",
    },
]

PROVIDER_MODELS = [
    {
        "id": 1,
        "provider_id": 1,
        "access_model_code": "openai-gpt-4o-mini",
        "provider_model_name": "gpt-4o-mini",
        "model_type": "llm",
        "status": 1,
        "currency": "USD",
    },
    {
        "id": 2,
        "provider_id": 2,
        "access_model_code": "deepseek-embedding",
        "provider_model_name": "deepseek-embedding",
        "model_type": "embedding",
        "status": 1,
        "currency": "USD",
    },
]

MODEL_NODES = [
    {
        "id": 1,
        "provider_id": 1,
        "provider_model_id": 1,
        "node_code": "openai-hk-01",
        "node_name": "OpenAI Hong Kong 01",
        "model_type": "llm",
        "endpoint_url": "https://gateway.example.com/openai/hk-01",
        "region": "hk",
        "status": 1,
        "health_status": "healthy",
        "weight": 100,
        "priority": 100,
        "max_concurrency": 50,
    },
    {
        "id": 2,
        "provider_id": 2,
        "provider_model_id": 2,
        "node_code": "deepseek-cn-01",
        "node_name": "DeepSeek CN 01",
        "model_type": "embedding",
        "endpoint_url": "https://gateway.example.com/deepseek/cn-01",
        "region": "cn",
        "status": 1,
        "health_status": "healthy",
        "weight": 80,
        "priority": 120,
        "max_concurrency": 100,
    },
]

AGGREGATED_MODELS = [
    {
        "id": 1,
        "organization_id": None,
        "aggregate_model_code": "chat-pro",
        "public_model_name": "chat-pro",
        "model_type": "llm",
        "description": "统一对外的对话模型",
        "status": 1,
        "default_routing_strategy": "priority",
    },
    {
        "id": 2,
        "organization_id": None,
        "aggregate_model_code": "text-embedding-pro",
        "public_model_name": "text-embedding-pro",
        "model_type": "embedding",
        "description": "统一对外的向量模型",
        "status": 1,
        "default_routing_strategy": "weight",
    },
]

AGGREGATE_MODEL_NODE_BINDINGS = [
    {
        "id": 1,
        "aggregate_model_id": 1,
        "node_id": 1,
        "traffic_role": "stable",
        "route_priority": 100,
        "weight": 100,
        "is_enabled": True,
        "is_fallback": False,
    },
    {
        "id": 2,
        "aggregate_model_id": 2,
        "node_id": 2,
        "traffic_role": "stable",
        "route_priority": 100,
        "weight": 100,
        "is_enabled": True,
        "is_fallback": False,
    },
]

PROJECT_MODEL_POLICIES = [
    {
        "id": 1,
        "project_id": 1,
        "aggregate_model_id": 1,
        "public_model_name": "chat-pro",
        "model_type": "llm",
        "is_visible": True,
        "node_id": 1,
        "route_priority": 100,
        "weight": 100,
        "is_enabled": True,
    },
    {
        "id": 2,
        "project_id": 1,
        "aggregate_model_id": 2,
        "public_model_name": "text-embedding-pro",
        "model_type": "embedding",
        "is_visible": True,
        "node_id": 2,
        "route_priority": 100,
        "weight": 100,
        "is_enabled": True,
    },
]

REQUEST_LOGS = [
    {
        "id": 1,
        "request_id": "req_demo_001",
        "organization_id": 1,
        "project_id": 1,
        "api_key_id": 1,
        "aggregate_model_id": 1,
        "provider_id": 1,
        "provider_model_id": 1,
        "node_id": 1,
        "public_model_name": "chat-pro",
        "model_type": "llm",
        "endpoint": "/v1/chat/completions",
        "request_method": "POST",
        "requester_ip": "127.0.0.1",
        "http_status": 200,
        "provider_status": "success",
        "latency_ms": 812,
    },
    {
        "id": 2,
        "request_id": "req_demo_002",
        "organization_id": 1,
        "project_id": 1,
        "api_key_id": 1,
        "aggregate_model_id": 2,
        "provider_id": 2,
        "provider_model_id": 2,
        "node_id": 2,
        "public_model_name": "text-embedding-pro",
        "model_type": "embedding",
        "endpoint": "/v1/embeddings",
        "request_method": "POST",
        "requester_ip": "127.0.0.1",
        "http_status": 200,
        "provider_status": "success",
        "latency_ms": 164,
    },
]

USAGE_RECORDS = [
    {
        "id": 1,
        "request_log_id": 1,
        "organization_id": 1,
        "project_id": 1,
        "api_key_id": 1,
        "aggregate_model_id": 1,
        "provider_id": 1,
        "provider_model_id": 1,
        "node_id": 1,
        "model_type": "llm",
        "input_tokens": 820,
        "output_tokens": 230,
        "total_tokens": 1050,
        "estimated_cost": Decimal("0.012800"),
        "currency": "USD",
    },
    {
        "id": 2,
        "request_log_id": 2,
        "organization_id": 1,
        "project_id": 1,
        "api_key_id": 1,
        "aggregate_model_id": 2,
        "provider_id": 2,
        "provider_model_id": 2,
        "node_id": 2,
        "model_type": "embedding",
        "input_tokens": 450,
        "output_tokens": 0,
        "total_tokens": 450,
        "estimated_cost": Decimal("0.001200"),
        "currency": "USD",
    },
]


def build_page(items: list[dict]) -> dict:
    page_items = deepcopy(items)
    return {
        "items": page_items,
        "page": 1,
        "page_size": len(page_items),
        "total": len(page_items),
    }


def get_overview_summary_data() -> dict:
    total_cost = sum((item["estimated_cost"] for item in USAGE_RECORDS), Decimal("0"))
    return {
        "total_requests": len(REQUEST_LOGS),
        "total_tokens": sum(item["total_tokens"] for item in USAGE_RECORDS),
        "total_cost": total_cost,
        "organization_count": len(ORGANIZATIONS),
        "project_count": len(PROJECTS),
        "key_count": len(API_KEYS),
        "provider_count": len(PROVIDERS),
        "model_count": len(PROVIDER_MODELS),
        "node_count": len(MODEL_NODES),
        "active_node_count": len([item for item in MODEL_NODES if item["status"] == 1]),
        "healthy_provider_count": len(
            [item for item in PROVIDERS if item["health_status"] == "healthy"]
        ),
    }
