from fastapi import APIRouter

from app.core.responses import success_response

router = APIRouter(prefix="/logs", tags=["日志审计"])


@router.get("/requests")
async def list_request_logs() -> dict:
    return success_response(
        {
            "items": [],
            "page": 1,
            "page_size": 20,
            "total": 0,
        }
    ).model_dump()
