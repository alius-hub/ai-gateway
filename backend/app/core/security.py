from __future__ import annotations

import hashlib
import hmac
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt

from app.core.config import get_settings

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 260000)
    return f"pbkdf2_sha256${salt.hex()}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    if password_hash.startswith("pbkdf2_sha256$"):
        try:
            _, salt, digest = password_hash.split("$")
            actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 260000)
            return hmac.compare_digest(actual, bytes.fromhex(digest))
        except ValueError:
            return False
    if password_hash.startswith("sha256$"):
        return hmac.compare_digest(
            hashlib.sha256(password.encode()).hexdigest(), password_hash.removeprefix("sha256$")
        )
    return hmac.compare_digest(password, password_hash)


def create_access_token(subject: str, expires_minutes: int | None = None) -> str:
    settings = get_settings()
    expire_at = datetime.now(UTC) + timedelta(
        minutes=expires_minutes or settings.access_token_expire_minutes
    )
    payload = {"sub": subject, "exp": expire_at}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise ValueError("Token 无效或已过期。") from exc

    subject = payload.get("sub")
    if not subject:
        raise ValueError("Token 缺少用户标识。")
    return payload
