import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, create_engine, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token
from app.db.base import Base
from app.db.models import AuditEvent, Project, User
from app.db.session import get_db
from app.main import app


@compiles(BigInteger, "sqlite")
def bigint_sqlite(_type, _compiler, **_kwargs):
    return "INTEGER"


def test_management_audit_records_success_without_request_body():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(
        engine, tables=[User.__table__, Project.__table__, AuditEvent.__table__],
    )
    session_factory = sessionmaker(bind=engine)
    with session_factory() as db:
        db.add_all([
            User(id=1, username="admin", email="a@example.com", password_hash="hash",
                 is_platform_admin=1),
            User(id=2, username="member", email="m@example.com", password_hash="hash"),
        ])
        db.commit()
    app.dependency_overrides[get_db] = lambda: session_factory()
    try:
        with patch("app.modules.audit.events.SessionLocal", session_factory):
            client = TestClient(app)
            admin = {"Authorization": f"Bearer {create_access_token('1')}"}
            member = {"Authorization": f"Bearer {create_access_token('2')}"}
            created = client.post("/api/admin/v1/projects", headers=admin,
                                  json={"name": "Audited", "owner_user_id": 1})
            assert created.status_code == 201
            assert client.post("/api/admin/v1/projects", headers=member,
                               json={"name": "Denied", "owner_user_id": 2}).status_code == 403
            page = client.get("/api/admin/v1/logs/audit-events", headers=admin).json()["data"]
            assert page["total"] == 1
            actors = client.get("/api/admin/v1/logs/audit-actors", headers=admin)
            assert actors.json()["data"] == [{"id": 1, "username": "admin"}]
            resources_endpoint = "/api/admin/v1/logs/audit-resources"
            assert client.get(resources_endpoint, headers=admin).json()["data"] == ["projects"]
            event = page["items"][0]
            assert event["actor_username"] == "admin"
            assert event["action"] == "create"
            assert event["resource"] == "projects"
            assert "Audited" not in str(event)
            assert client.get("/api/admin/v1/logs/audit-events", headers=member).status_code == 403
            assert client.get("/api/admin/v1/logs/audit-actors", headers=member).status_code == 403
            assert client.get(resources_endpoint, headers=member).status_code == 403
            with session_factory() as db:
                assert len(db.scalars(select(AuditEvent)).all()) == 1
                db.add_all([
                    AuditEvent(
                        actor_user_id=1 if index % 2 else 2,
                        actor_username="admin" if index % 2 else "member",
                        action="update" if index % 2 else "delete",
                        resource="projects" if index <= 12 else "users",
                        method="PATCH" if index % 2 else "DELETE",
                        path=f"/api/admin/v1/projects/{index}",
                        status_code=200, created_at=datetime.now(UTC) + timedelta(seconds=index),
                    ) for index in range(1, 26)
                ])
                db.commit()
            assert client.get(resources_endpoint, headers=admin).json()["data"] == [
                "projects", "users",
            ]
            endpoint = "/api/admin/v1/logs/audit-events"
            assert client.get(endpoint, headers=admin, params={
                "resource": "users",
            }).json()["data"]["total"] == 13
            filters = json.dumps({
                "mode": "and", "conditions": [
                    {"field": "actor_username", "operator": "eq", "value": "admin"},
                    {"field": "resource", "operator": "eq", "value": "projects"},
                ],
            })
            first = client.get(endpoint, headers=admin, params={
                "page": 1, "page_size": 3, "filters": filters,
            }).json()["data"]
            second = client.get(endpoint, headers=admin, params={
                "page": 2, "page_size": 3, "filters": filters,
            }).json()["data"]
            assert first["total"] == second["total"] == 7
            assert first["page_size"] == 3
            assert len(first["items"]) == len(second["items"]) == 3
            assert {item["id"] for item in first["items"]}.isdisjoint(
                item["id"] for item in second["items"]
            )
            assert all(item["actor_username"] == "admin"
                       and item["resource"] == "projects" for item in first["items"])
            assert len(client.get(endpoint, headers=admin, params={
                "page": 3, "page_size": 3, "filters": filters,
            }).json()["data"]["items"]) == 1
            assert client.get(endpoint, headers=admin, params={
                "page": 4, "page_size": 3, "filters": filters,
            }).json()["data"]["items"] == []
            either = json.dumps({
                "mode": "or", "conditions": [
                    {"field": "action", "operator": "eq", "value": "login"},
                    {"field": "resource", "operator": "eq", "value": "users"},
                ],
            })
            assert client.get(endpoint, headers=admin, params={
                "filters": either, "action": "delete",
            }).json()["data"]["total"] == 6
            invalid = json.dumps({
                "mode": "and", "conditions": [
                    {"field": "password_hash", "operator": "contains", "value": "test"},
                ],
            })
            assert client.get(endpoint, headers=admin, params={
                "filters": invalid,
            }).status_code == 422
            assert client.get(endpoint, headers=admin, params={"page_size": 101}).status_code == 422
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
