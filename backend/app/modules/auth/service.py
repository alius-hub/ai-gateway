from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.security import create_access_token, decode_access_token, verify_password
from app.db.models import User
from app.modules.auth.schemas import LoginResponse, UserInfo


def _build_user_info(user: User) -> UserInfo:
    return UserInfo(
        id=user.id,
        username=user.username,
        email=user.email,
        display_name=user.nickname or user.username,
        roles=["platform_admin"] if user.is_platform_admin else [],
    )


def authenticate_user(db: Session, username: str, password: str) -> LoginResponse:
    identity = username.strip()
    user = db.scalar(
        select(User).where(
            or_(
                User.username == identity,
                User.email == identity,
            )
        )
    )
    if not user or user.deleted_at or user.status != 1 or not verify_password(password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误。",
        )

    user_info = _build_user_info(user)
    return LoginResponse(
        access_token=create_access_token(str(user_info.id)),
        user_info=user_info,
    )


def get_current_user(db: Session, token: str) -> UserInfo:
    try:
        user = db.get(User, int(decode_access_token(token)["sub"]))
    except ValueError:
        user = None
    if user and user.status == 1 and not user.deleted_at:
        return _build_user_info(user)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="登录状态已失效，请重新登录。",
    )
