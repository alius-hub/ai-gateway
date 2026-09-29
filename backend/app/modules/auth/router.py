# ruff: noqa: B008
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.responses import success_response
from app.db.models import AuditEvent
from app.db.session import get_db
from app.modules.auth.schemas import LoginRequest
from app.modules.auth.service import authenticate_user, get_current_user

router = APIRouter(prefix="/auth", tags=["认证与用户"])
bearer_scheme = HTTPBearer(auto_error=True)


@router.post("/login")
async def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    result = authenticate_user(db, payload.username, payload.password)
    db.add(AuditEvent(
        actor_user_id=result.user_info.id, actor_username=result.user_info.username,
        action="login", resource="auth", method="POST", path=request.url.path,
        ip_address=request.client.host if request.client else None,
        status_code=200, created_at=datetime.now(UTC),
    ))
    db.commit()
    return success_response(result).model_dump()


@router.get("/me")
async def me(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> dict:
    return success_response(get_current_user(db, credentials.credentials)).model_dump()
