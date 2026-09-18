from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.demo_data import ORGANIZATIONS, build_page
from app.core.responses import success_response
from app.db.models import Organization
from app.db.session import get_db

router = APIRouter(prefix="/organizations", tags=["组织管理"])


@router.get("")
async def list_organizations(db: Session = Depends(get_db)) -> dict:
    try:
        organizations = db.scalars(select(Organization).order_by(Organization.id)).all()
        data = build_page(
            [
                {
                    "id": item.id,
                    "name": item.name,
                    "code": item.code,
                    "status": item.status,
                    "description": item.description,
                }
                for item in organizations
            ]
        )
    except SQLAlchemyError:
        data = build_page(ORGANIZATIONS)

    return success_response(data).model_dump()
