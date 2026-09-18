from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.demo_data import PROJECTS, build_page
from app.core.responses import success_response
from app.db.models import Project
from app.db.session import get_db

router = APIRouter(prefix="/projects", tags=["项目管理"])


@router.get("")
async def list_projects(db: Session = Depends(get_db)) -> dict:
    try:
        projects = db.scalars(select(Project).order_by(Project.id)).all()
        data = build_page(
            [
                {
                    "id": item.id,
                    "organization_id": item.organization_id,
                    "name": item.name,
                    "code": item.code,
                    "environment": item.environment,
                    "status": item.status,
                    "description": item.description,
                }
                for item in projects
            ]
        )
    except SQLAlchemyError:
        data = build_page(PROJECTS)

    return success_response(data).model_dump()
