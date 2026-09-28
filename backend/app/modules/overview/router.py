# ruff: noqa: B008
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.responses import success_response
from app.db.models import User
from app.db.session import get_db
from app.modules.identity.router import actor, require_platform
from app.modules.overview.service import get_overview_activity, get_overview_summary

router = APIRouter(prefix="/overview", tags=["平台总览"])


@router.get("/summary")
async def summary(db: Session = Depends(get_db), user: User = Depends(actor)) -> dict:
    require_platform(user)
    return success_response(get_overview_summary(db).model_dump(mode="json")).model_dump()


@router.get("/activity")
async def activity(
    days: int = Query(7, ge=7, le=30),
    db: Session = Depends(get_db),
    user: User = Depends(actor),
) -> dict:
    require_platform(user)
    return success_response(get_overview_activity(db, days).model_dump(mode="json")).model_dump()
