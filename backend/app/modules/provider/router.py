from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.demo_data import PROVIDERS, build_page
from app.core.responses import success_response
from app.db.models import Provider
from app.db.session import get_db

router = APIRouter(prefix="/providers", tags=["供应商管理"])


@router.get("")
async def list_providers(db: Session = Depends(get_db)) -> dict:
    try:
        providers = db.scalars(select(Provider).order_by(Provider.id)).all()
        data = build_page(
            [
                {
                    "id": item.id,
                    "name": item.name,
                    "code": item.code,
                    "provider_type": item.provider_type,
                    "base_url": item.base_url,
                    "status": item.status,
                    "health_status": item.health_status,
                }
                for item in providers
            ]
        )
    except SQLAlchemyError:
        data = build_page(PROVIDERS)

    return success_response(data).model_dump()
