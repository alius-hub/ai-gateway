from __future__ import annotations

# ruff: noqa: B008
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.responses import success_response
from app.db.models import GatewayLogSettings, User
from app.db.session import get_db
from app.modules.identity.router import actor, require_platform

router = APIRouter(prefix="/settings/log-archive", tags=["平台设置"])


class LogArchivePolicy(BaseModel):
    image_mode: Literal["content_only", "mirror_images"]


@router.get("")
async def get_log_archive_policy(
    db: Session = Depends(get_db), user: User = Depends(actor),
) -> dict:
    require_platform(user)
    item = db.get(GatewayLogSettings, 1)
    return success_response({
        "image_mode": item.image_mode if item else "content_only",
    }).model_dump()


@router.put("")
async def update_log_archive_policy(
    payload: LogArchivePolicy,
    db: Session = Depends(get_db),
    user: User = Depends(actor),
) -> dict:
    require_platform(user)
    item = db.get(GatewayLogSettings, 1)
    if item is None:
        item = GatewayLogSettings(id=1, image_mode=payload.image_mode)
        db.add(item)
    else:
        item.image_mode = payload.image_mode
    db.commit()
    return success_response({"image_mode": item.image_mode}).model_dump()
