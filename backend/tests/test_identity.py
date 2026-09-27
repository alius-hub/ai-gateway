import unittest

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token
from app.db.base import Base
from app.db.models import Organization, OrganizationMember, Project, ProjectMember, User, UserGroup, UserGroupMember
from app.db.session import get_db
from app.main import app
from app.modules.identity.router import organization_role, require_access, validate_parent


@compiles(BigInteger, "sqlite")
def compile_bigint_for_sqlite(_type, _compiler, **_kwargs):
    return "INTEGER"


class IdentityPermissionsTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(
            self.engine,
            tables=[User.__table__, Organization.__table__, OrganizationMember.__table__,
                    UserGroup.__table__, UserGroupMember.__table__,
                    Project.__table__, ProjectMember.__table__],
        )
        self.db = Session(self.engine)
        self.admin = User(id=1, username="admin", email="admin@example.com", password_hash="hash", is_platform_admin=1)
        self.manager = User(id=2, username="manager", email="manager@example.com", password_hash="hash")
        self.viewer = User(id=3, username="viewer", email="viewer@example.com", password_hash="hash")
        self.root = Organization(id=1, name="Root", code="root", owner_user_id=1)
        self.child = Organization(id=2, name="Child", code="child", parent_id=1, owner_user_id=1)
        self.db.add_all([self.admin, self.manager, self.viewer, self.root, self.child])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_cycle_and_disabled_parent_are_rejected(self):
        validate_parent(self.db, 1, 2)
        with self.assertRaises(HTTPException):
            validate_parent(self.db, 2, 1)
        self.root.status = 0
        self.db.flush()
        with self.assertRaises(HTTPException):
            validate_parent(self.db, 1)

    def test_organization_admin_inherits_to_child(self):
        self.db.add(OrganizationMember(
            id=1, organization_id=1, user_id=2, role="org_admin", status=1))
        self.db.commit()
        self.assertEqual(organization_role(self.db, self.manager, 2), "org_admin")
        require_access(self.db, self.manager, "organizations", self.child, write=True)
        with self.assertRaises(HTTPException):
            require_access(self.db, self.manager, "users", self.viewer, write=True)

    def test_group_membership_does_not_grant_organization_access(self):
        self.db.add(UserGroup(
            id=1, group_name="Readers", group_code="readers", created_by=1, status=1))
        self.db.add(UserGroupMember(id=1, group_id=1, user_id=3))
        self.db.commit()
        self.assertIsNone(organization_role(self.db, self.viewer, 2))
        with self.assertRaises(HTTPException):
            require_access(self.db, self.viewer, "organizations", self.child)
        self.db.add(OrganizationMember(id=1, organization_id=1, user_id=3, role="readonly", status=1))
        self.db.commit()
        self.assertEqual(organization_role(self.db, self.viewer, 2), "readonly")
        self.db.get(OrganizationMember, 1).status = 0
        self.db.commit()
        self.assertIsNone(organization_role(self.db, self.viewer, 2))

    def test_new_organization_can_have_no_members(self):
        def session_override():
            yield self.db

        app.dependency_overrides[get_db] = session_override
        try:
            client = TestClient(app)
            headers = {"Authorization": f"Bearer {create_access_token('1')}"}
            path = "/api/admin/v1/organizations"
            created = client.post(path, json={"name": "Empty", "code": "empty"}, headers=headers)
            self.assertEqual(created.status_code, 201, created.text)
            org = created.json()["data"]
            self.assertEqual(org["owner_user_id"], self.admin.id)
            members_path = f"{path}/{org['id']}/members"
            self.assertEqual(client.get(members_path, headers=headers).json()["data"], [])
            self.assertEqual(organization_role(self.db, self.admin, org["id"]), "org_admin")

            added = client.post(
                members_path, json={"user_id": self.admin.id, "role": "member"}, headers=headers,
            )
            self.assertEqual(added.status_code, 201, added.text)
            removed = client.delete(f"{members_path}/{self.admin.id}", headers=headers)
            self.assertEqual(removed.status_code, 200, removed.text)
            self.assertEqual(client.get(members_path, headers=headers).json()["data"], [])

            child = client.post(
                path, json={"name": "Empty Child", "code": "empty-child", "parent_id": org["id"]},
                headers=headers,
            )
            self.assertEqual(child.status_code, 201, child.text)
            self.assertEqual(client.get(f"{path}/{child.json()['data']['id']}/members", headers=headers).json()["data"], [])
        finally:
            app.dependency_overrides.clear()

    def test_independent_group_creation_and_membership(self):
        def session_override():
            yield self.db

        app.dependency_overrides[get_db] = session_override
        try:
            client = TestClient(app)
            admin_headers = {"Authorization": f"Bearer {create_access_token('1')}"}
            manager_headers = {"Authorization": f"Bearer {create_access_token('2')}"}
            path = "/api/admin/v1/user-groups"
            created = client.post(path, json={"group_name": "Readers", "group_code": "readers"}, headers=admin_headers)
            self.assertEqual(created.status_code, 201, created.text)
            group = created.json()["data"]
            self.assertNotIn("organization_id", group)
            self.assertNotIn("role", group)
            listed = client.get(path, headers=manager_headers)
            self.assertEqual(listed.status_code, 200, listed.text)
            self.assertEqual(listed.json()["data"]["total"], 1)
            added = client.post(f"{path}/{group['id']}/members", json={"user_id": 3}, headers=admin_headers)
            self.assertEqual(added.status_code, 201, added.text)
            self.assertEqual(client.get(f"{path}/{group['id']}/members", headers=manager_headers).status_code, 403)
            self.assertIsNone(organization_role(self.db, self.viewer, 1))
            self.assertEqual(client.get(f"{path}?organization_id=1", headers=admin_headers).status_code, 422)
            forbidden = client.post(path, json={"group_name": "Other", "group_code": "other"}, headers=manager_headers)
            self.assertEqual(forbidden.status_code, 403)
            invalid = client.post(
                path, json={"organization_id": 1, "group_name": "Scoped", "group_code": "scoped"},
                headers=admin_headers,
            )
            self.assertEqual(invalid.status_code, 422)
        finally:
            app.dependency_overrides.clear()

    def test_codes_are_generated_when_left_blank(self):
        def session_override():
            yield self.db

        app.dependency_overrides[get_db] = session_override
        try:
            client = TestClient(app)
            headers = {"Authorization": f"Bearer {create_access_token('1')}"}
            for kind, name_field, code_field, prefix in (
                ("user-groups", "group_name", "group_code", "grp"),
                ("organizations", "name", "code", "org"),
                ("projects", "name", "code", "prj"),
            ):
                path = f"/api/admin/v1/{kind}"
                generated = []
                for value in (None, "", "   "):
                    body = {name_field: f"{kind}-{len(generated)}"}
                    if value is not None:
                        body[code_field] = value
                    response = client.post(path, json=body, headers=headers)
                    self.assertEqual(response.status_code, 201, response.text)
                    code = response.json()["data"][code_field]
                    self.assertRegex(code, rf"^{prefix}_[0-9a-f]{{32}}$")
                    generated.append(code)
                self.assertEqual(len(set(generated)), 3)

                manual = client.post(
                    path, json={name_field: "Manual", code_field: "my-code"}, headers=headers,
                )
                self.assertEqual(manual.status_code, 201, manual.text)
                self.assertEqual(manual.json()["data"][code_field], "my-code")
                missing_name = client.post(path, json={code_field: "another-code"}, headers=headers)
                self.assertEqual(missing_name.status_code, 422, missing_name.text)
        finally:
            app.dependency_overrides.clear()

    def test_platform_project_without_organization(self):
        def session_override():
            yield self.db

        app.dependency_overrides[get_db] = session_override
        try:
            client = TestClient(app)
            admin_headers = {"Authorization": f"Bearer {create_access_token('1')}"}
            manager_headers = {"Authorization": f"Bearer {create_access_token('2')}"}
            owner_headers = {"Authorization": f"Bearer {create_access_token('3')}"}
            path = "/api/admin/v1/projects"
            created = client.post(
                path, json={"name": "Global", "code": "global", "owner_user_id": 3},
                headers=admin_headers,
            )
            self.assertEqual(created.status_code, 201, created.text)
            project = created.json()["data"]
            self.assertIsNone(project["organization_id"])
            members_path = f"{path}/{project['id']}/members"
            self.assertEqual(client.get(members_path, headers=owner_headers).json()["data"], [])
            self.assertEqual(client.post(
                members_path, json={"user_id": 3, "role": "viewer"}, headers=owner_headers,
            ).status_code, 201)
            self.assertEqual(client.patch(
                f"{members_path}/3", json={"role": "developer"}, headers=owner_headers,
            ).status_code, 200)
            self.db.add(OrganizationMember(organization_id=1, user_id=2, role="org_admin", status=1))
            self.db.commit()
            self.assertEqual(client.get(f"{path}/{project['id']}", headers=manager_headers).status_code, 403)
            self.assertEqual(client.get(path, params={"scope": "platform"}, headers=owner_headers).json()["data"]["total"], 1)
            self.assertEqual(client.get(path, params={"organization_id": 1}, headers=admin_headers).json()["data"]["total"], 0)
            self.assertEqual(client.get(path, params={"scope": "platform", "organization_id": 1}, headers=admin_headers).status_code, 422)
            added = client.post(
                f"{path}/{project['id']}/members", json={"user_id": 2, "role": "developer"},
                headers=owner_headers,
            )
            self.assertEqual(added.status_code, 201, added.text)
            self.assertEqual(client.get(path, headers=manager_headers).json()["data"]["total"], 1)
            self.assertEqual(client.patch(f"{path}/{project['id']}", json={"name": "Other"}, headers=manager_headers).status_code, 403)
            self.assertEqual(client.patch(f"{path}/{project['id']}", json={"organization_id": 1}, headers=admin_headers).status_code, 422)
            disabled = client.patch(
                f"{path}/{project['id']}/members/2", json={"status": 0}, headers=owner_headers,
            )
            self.assertEqual(disabled.status_code, 200, disabled.text)
            self.assertEqual(client.get(f"{path}/{project['id']}", headers=manager_headers).status_code, 403)
            self.assertEqual(client.get(path, headers=manager_headers).json()["data"]["total"], 0)
            self.assertEqual(client.post(path, json={"name": "Denied", "code": "denied"}, headers=manager_headers).status_code, 403)
            self.assertEqual(client.delete(f"{members_path}/2", headers=owner_headers).status_code, 200)
            self.assertEqual(client.delete(f"{members_path}/3", headers=owner_headers).status_code, 200)
            self.assertEqual(client.get(members_path, headers=owner_headers).json()["data"], [])
            self.assertEqual(client.get(f"{path}/{project['id']}", headers=owner_headers).status_code, 200)
        finally:
            app.dependency_overrides.clear()

    def test_organization_and_project_members_can_both_be_cleared(self):
        def session_override():
            yield self.db

        app.dependency_overrides[get_db] = session_override
        try:
            client = TestClient(app)
            admin_headers = {"Authorization": f"Bearer {create_access_token('1')}"}
            owner_headers = {"Authorization": f"Bearer {create_access_token('2')}"}
            self.db.add(OrganizationMember(organization_id=1, user_id=2, role="member", status=1))
            self.db.commit()
            created = client.post(
                "/api/admin/v1/projects",
                json={"name": "Scoped", "code": "scoped", "organization_id": 1, "owner_user_id": 2},
                headers=admin_headers,
            )
            self.assertEqual(created.status_code, 201, created.text)
            project_id = created.json()["data"]["id"]
            org_members = "/api/admin/v1/organizations/1/members"
            project_members = f"/api/admin/v1/projects/{project_id}/members"
            self.assertEqual(client.get(project_members, headers=owner_headers).json()["data"], [])
            self.assertEqual(client.post(
                project_members, json={"user_id": 2, "role": "viewer"}, headers=owner_headers,
            ).status_code, 201)
            self.assertEqual(client.delete(f"{org_members}/2", headers=admin_headers).status_code, 200)
            self.assertEqual(client.get(org_members, headers=admin_headers).json()["data"], [])
            self.assertEqual(client.delete(f"{project_members}/2", headers=owner_headers).status_code, 200)
            self.assertEqual(client.get(project_members, headers=owner_headers).json()["data"], [])
            self.assertEqual(client.get(f"/api/admin/v1/projects/{project_id}", headers=owner_headers).status_code, 200)
            self.assertEqual(client.get("/api/admin/v1/projects", headers=owner_headers).json()["data"]["total"], 1)
        finally:
            app.dependency_overrides.clear()

    def test_changing_project_owner_does_not_add_member(self):
        def session_override():
            yield self.db

        app.dependency_overrides[get_db] = session_override
        try:
            client = TestClient(app)
            headers = {"Authorization": f"Bearer {create_access_token('1')}"}
            path = "/api/admin/v1/projects"
            created = client.post(path, json={"name": "Empty", "code": "empty"}, headers=headers)
            self.assertEqual(created.status_code, 201, created.text)
            project_id = created.json()["data"]["id"]
            members_path = f"{path}/{project_id}/members"
            self.assertEqual(client.get(members_path, headers=headers).json()["data"], [])
            changed = client.patch(f"{path}/{project_id}", json={"owner_user_id": 2}, headers=headers)
            self.assertEqual(changed.status_code, 200, changed.text)
            self.assertEqual(changed.json()["data"]["owner_user_id"], 2)
            self.assertEqual(client.get(members_path, headers=headers).json()["data"], [])
            manager_headers = {"Authorization": f"Bearer {create_access_token('2')}"}
            self.assertEqual(client.get(f"{path}/{project_id}", headers=manager_headers).status_code, 200)
        finally:
            app.dependency_overrides.clear()

    def test_tree_endpoint_and_restricted_user_update(self):
        def session_override():
            yield self.db

        app.dependency_overrides[get_db] = session_override
        try:
            client = TestClient(app)
            headers = {"Authorization": f"Bearer {create_access_token('2')}"}
            self.db.add(OrganizationMember(
                id=1, organization_id=1, user_id=2, role="org_admin", status=1))
            self.db.commit()
            response = client.get("/api/admin/v1/organizations/tree", headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["data"][0]["children"][0]["name"], "Child")
            forbidden = client.patch("/api/admin/v1/users/3", json={"status": 0}, headers=headers)
            self.assertEqual(forbidden.status_code, 403)
        finally:
            app.dependency_overrides.clear()


if __name__ == "__main__":
    unittest.main()
