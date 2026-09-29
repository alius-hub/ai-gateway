from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings
from app.core.security import decode_access_token
from app.db.models import AuditEvent, User
from app.db.session import SessionLocal

WRITE_METHODS = {"POST": "create", "PUT": "update", "PATCH": "update", "DELETE": "delete"}
READ_ONLY_POST_SUFFIXES = ("/simulate", "/probe")
logger = logging.getLogger(__name__)


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        prefix = get_settings().admin_api_prefix.rstrip("/")
        if (request.method not in WRITE_METHODS or not 200 <= response.status_code < 300
                or not request.url.path.startswith(prefix + "/")
                or request.url.path == prefix + "/auth/login"
                or request.url.path.startswith(prefix + "/playground/")
                or request.url.path.endswith(READ_ONLY_POST_SUFFIXES)):
            return response
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            return response
        try:
            user_id = int(decode_access_token(header[7:])["sub"])
            with SessionLocal() as db:
                user = db.get(User, user_id)
                if user is None:
                    return response
                relative = request.url.path[len(prefix):].strip("/")
                resource = relative.split("/", 1)[0]
                action = WRITE_METHODS[request.method]
                if relative.endswith("/rotate"):
                    action = "rotate"
                elif relative.endswith("/reset-password"):
                    action = "reset_password"
                db.add(AuditEvent(
                    actor_user_id=user.id, actor_username=user.username,
                    action=action, resource=resource,
                    method=request.method, path=request.url.path[:512],
                    ip_address=client_ip(request), status_code=response.status_code,
                    created_at=datetime.now(UTC),
                ))
                db.commit()
        except Exception:
            # Auditing must not turn an already completed mutation into a retryable error.
            logger.exception("Failed to write management audit event")
        return response
