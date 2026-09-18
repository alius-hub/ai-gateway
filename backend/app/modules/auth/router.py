from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.responses import success_response
from app.db.session import get_db
from app.modules.auth.schemas import LoginRequest
from app.modules.auth.service import authenticate_user, get_current_user

router = APIRouter(prefix="/auth", tags=["认证与用户"])
bearer_scheme = HTTPBearer(auto_error=True)


@router.post("/login")
async def login(payload: LoginRequest, db: Session = Depends(get_db)) -> dict:
    return success_response(authenticate_user(db, payload.username, payload.password)).model_dump()


@router.get("/me")
async def me(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> dict:
    return success_response(get_current_user(db, credentials.credentials)).model_dump()
