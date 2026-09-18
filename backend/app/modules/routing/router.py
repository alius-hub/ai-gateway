from fastapi import APIRouter

from app.core.responses import success_response

router = APIRouter(prefix="/routing", tags=["路由策略"])


@router.get("/policies")
async def list_policies() -> dict:
    return success_response(
        {
            "items": [
                {
                    "id": 1,
                    "project_id": 1,
                    "aggregate_model_id": 1,
                    "public_model_name": "chat-pro",
                    "route_priority": 100,
                    "weight": 100,
                    "is_enabled": True,
                }
            ],
            "page": 1,
            "page_size": 20,
            "total": 1,
        }
    ).model_dump()


@router.post("/debug")
async def debug_route() -> dict:
    return success_response(
        {
            "policy_id": 1,
            "candidate_nodes": [1],
            "filtered_reasons": [],
            "selected_node_id": 1,
            "strategy": "priority_weighted",
        }
    ).model_dump()
