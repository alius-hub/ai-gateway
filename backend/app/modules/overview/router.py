from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.responses import success_response
from app.db.session import get_db
from app.modules.overview.service import get_overview_summary

router = APIRouter(prefix="/overview", tags=["平台总览"])


@router.get("/summary")
async def summary(db: Session = Depends(get_db)) -> dict:
    return success_response(get_overview_summary(db).model_dump(mode="json")).model_dump()
