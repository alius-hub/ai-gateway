from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.demo_data import API_KEYS, build_page
from app.core.responses import success_response
from app.db.models import ApiKey
from app.db.session import get_db

router = APIRouter(prefix="/credentials", tags=["凭证管理"])


@router.get("/project-keys")
async def list_project_keys(db: Session = Depends(get_db)) -> dict:
    try:
        api_keys = db.scalars(select(ApiKey).order_by(ApiKey.id)).all()
        data = build_page(
            [
                {
                    "id": item.id,
                    "organization_id": item.organization_id,
                    "project_id": item.project_id,
                    "name": item.name,
                    "scope_type": item.scope_type,
                    "status": item.status,
                    "key_prefix": item.key_prefix,
                }
                for item in api_keys
            ]
        )
    except SQLAlchemyError:
        data = build_page(API_KEYS)

    return success_response(data).model_dump()
