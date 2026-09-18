from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.demo_data import USERS
from app.core.security import create_access_token, decode_access_token, verify_password
from app.db.models import User
from app.modules.auth.schemas import LoginResponse, UserInfo


DEMO_ROLES = ["platform_admin"]


def _build_user_info(
    user_id: int,
    username: str,
    email: str | None,
    nickname: str | None,
) -> UserInfo:
    return UserInfo(
        id=user_id,
        username=username,
        email=email,
        display_name=nickname or username,
        roles=DEMO_ROLES,
    )


def _find_demo_user(identity: str) -> dict | None:
    identity_lower = identity.strip().lower()
    for user in USERS:
        if user["username"].lower() == identity_lower or user["email"].lower() == identity_lower:
            return user
    return None


def authenticate_user(db: Session, username: str, password: str) -> LoginResponse:
    identity = username.strip()
    user_info: UserInfo | None = None
    password_hash: str | None = None

    try:
        user = db.scalar(
            select(User).where(
                or_(
                    User.username == identity,
                    User.email == identity,
                )
            )
        )
        if user and user.status == 1:
            user_info = _build_user_info(user.id, user.username, user.email, user.nickname)
            password_hash = user.password_hash
    except SQLAlchemyError:
        user = None

    if not user_info:
        demo_user = _find_demo_user(identity)
        if demo_user and demo_user["status"] == 1:
            user_info = _build_user_info(
                demo_user["id"],
                demo_user["username"],
                demo_user["email"],
                demo_user["nickname"],
            )
            password_hash = demo_user["password_hash"]

    if not user_info or not password_hash or not verify_password(password, password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误。",
        )

    return LoginResponse(
        access_token=create_access_token(str(user_info.id)),
        user_info=user_info,
    )


def get_current_user(db: Session, token: str) -> UserInfo:
    payload = decode_access_token(token)
    subject = payload["sub"]

    try:
        user = db.get(User, int(subject))
        if user and user.status == 1:
            return _build_user_info(user.id, user.username, user.email, user.nickname)
    except (SQLAlchemyError, ValueError):
        pass

    demo_user = next((item for item in USERS if str(item["id"]) == str(subject)), None)
    if demo_user and demo_user["status"] == 1:
        return _build_user_info(
            demo_user["id"],
            demo_user["username"],
            demo_user["email"],
            demo_user["nickname"],
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="登录状态已失效，请重新登录。",
    )
