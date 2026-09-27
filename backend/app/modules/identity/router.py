from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.responses import success_response
from app.core.security import hash_password
from app.db.models import (
    Organization, OrganizationMember, Project, ProjectMember, User, UserGroup, UserGroupMember,
)
from app.db.session import get_db
from app.modules.auth.service import get_current_user

router = APIRouter(tags=["用户与权限"])
bearer = HTTPBearer()


class EntityPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str | None = Field(default=None, min_length=2, max_length=64)
    email: str | None = Field(default=None, min_length=3, max_length=128)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    nickname: str | None = Field(default=None, max_length=64)
    is_platform_admin: Literal[0, 1] | None = None
    name: str | None = Field(default=None, min_length=1, max_length=128)
    code: str | None = Field(default=None, max_length=64)
    group_name: str | None = Field(default=None, min_length=1, max_length=128)
    group_code: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=255)
    organization_id: int | None = None
    parent_id: int | None = Field(default=None, gt=0)
    owner_user_id: int | None = None
    environment: Literal["dev", "test", "prod"] | None = None
    role: Literal["org_admin", "member", "readonly"] | None = None
    status: Literal[0, 1] | None = None


class MemberPayload(BaseModel):
    user_id: int
    role: str | None = Field(default=None, max_length=32)
    status: Literal[0, 1] = 1


class MemberUpdate(BaseModel):
    role: str | None = Field(default=None, max_length=32)
    status: Literal[0, 1] | None = None


class PasswordReset(BaseModel):
    password: str = Field(min_length=8, max_length=128)


@dataclass(frozen=True)
class Spec:
    model: type
    fields: tuple[str, ...]
    required: tuple[str, ...]
    name: str


SPECS = {
    "users": Spec(
        User, ("username", "email", "nickname", "is_platform_admin", "status"),
        ("username", "email", "password"), "username",
    ),
    "user-groups": Spec(
        UserGroup, ("group_name", "group_code", "description", "status"),
        ("group_name",), "group_name",
    ),
    "organizations": Spec(
        Organization, ("name", "code", "description", "parent_id", "status"), ("name",), "name",
    ),
    "projects": Spec(
        Project, ("organization_id", "name", "code", "environment", "description", "status", "owner_user_id"),
        ("name",), "name",
    ),
}
CODE_FIELDS = {
    "user-groups": ("group_code", "grp"),
    "organizations": ("code", "org"),
    "projects": ("code", "prj"),
}
MEMBERS = {
    "user-groups": (UserGroupMember, "group_id"),
    "organizations": (OrganizationMember, "organization_id"),
    "projects": (ProjectMember, "project_id"),
}
ROLES = {
    "organizations": ("org_admin", "member", "readonly"),
    "projects": ("project_admin", "developer", "viewer"),
}


def is_platform_admin(user: User) -> bool:
    return bool(user.is_platform_admin)


def actor(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    info = get_current_user(db, credentials.credentials)
    return db.get(User, info.id)


def require_platform(user: User) -> None:
    if not is_platform_admin(user):
        raise HTTPException(403, "仅平台管理员可执行该操作。")


def organization_role(db: Session, user: User, organization_id: int) -> str | None:
    if is_platform_admin(user):
        return "org_admin"
    current = organization_id
    seen: set[int] = set()
    effective: str | None = None
    while current and current not in seen:
        seen.add(current)
        org = db.get(Organization, current)
        if not org or org.deleted_at or org.status != 1:
            return None
        if org.owner_user_id == user.id:
            return "org_admin"
        direct = db.scalar(select(OrganizationMember).where(
            OrganizationMember.organization_id == current,
            OrganizationMember.user_id == user.id, OrganizationMember.status == 1))
        roles = [direct.role] if direct else []
        if "org_admin" in roles:
            return "org_admin"
        if "member" in roles:
            effective = "member"
        elif "readonly" in roles and effective is None:
            effective = "readonly"
        current = org.parent_id
    return effective


def require_access(db: Session, user: User, kind: str, item=None, *,
                   organization_id: int | None = None, write: bool = False) -> None:
    if is_platform_admin(user):
        return
    if kind == "users":
        require_platform(user)
    if kind == "user-groups":
        if write:
            require_platform(user)
        return
    if kind == "projects" and item is not None and item.organization_id is None:
        member = db.scalar(select(ProjectMember).where(
            ProjectMember.project_id == item.id, ProjectMember.user_id == user.id,
            ProjectMember.status == 1))
        if item.owner_user_id == user.id or (member and (not write or member.role == "project_admin")):
            return
        raise HTTPException(403, "无权操作该平台级项目。")
    if kind == "organizations":
        organization_id = item.id if item else organization_id
    elif item is not None:
        organization_id = item.organization_id
    if organization_id is None:
        raise HTTPException(403, "无权操作该组织。")
    role = organization_role(db, user, organization_id)
    if kind == "projects" and item is not None and role != "org_admin":
        org = db.get(Organization, organization_id)
        if not org or org.deleted_at or org.status != 1:
            raise HTTPException(403, "所属组织已停用。")
        if item.owner_user_id == user.id:
            return
        member = db.scalar(select(ProjectMember).where(
            ProjectMember.project_id == item.id, ProjectMember.user_id == user.id,
            ProjectMember.status == 1))
        if member:
            if member.role == "project_admin":
                role = "org_admin"
            elif role is None:
                role = "member"
    if not role or (write and role != "org_admin"):
        raise HTTPException(403, "无权操作该资源。")


def spec_for(kind: str) -> Spec:
    if kind not in SPECS:
        raise HTTPException(404, "资源不存在。")
    return SPECS[kind]


def active(db: Session, model: type, id_: int):
    item = db.get(model, id_)
    if not item or (hasattr(item, "deleted_at") and item.deleted_at is not None):
        raise HTTPException(404, "记录不存在。")
    return item


def serialize(item) -> dict:
    fields = {c.key: getattr(item, c.key) for c in item.__table__.columns}
    fields.pop("password_hash", None)
    fields.pop("deleted_at", None)
    return fields


def save(db: Session, item) -> dict:
    try:
        db.add(item)
        db.commit()
        db.refresh(item)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "编码、用户名、邮箱或成员关系已存在。") from exc
    return success_response(serialize(item)).model_dump(mode="json")


def validate_owner(db: Session, user_id: int) -> None:
    user = active(db, User, user_id)
    if user.status != 1:
        raise HTTPException(400, "负责人必须是启用的用户。")


def validate_org(db: Session, organization_id: int) -> None:
    org = active(db, Organization, organization_id)
    if org.status != 1:
        raise HTTPException(400, "所属组织已停用。")


def validate_membership(db: Session, organization_id: int, user_id: int) -> None:
    org = active(db, Organization, organization_id)
    membership = db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == user_id,
            OrganizationMember.status == 1,
        )
    )
    if org.owner_user_id != user_id and not membership:
        raise HTTPException(400, "用户必须先加入所属组织。")


def validate_parent(db: Session, parent_id: int | None, item_id: int | None = None) -> None:
    seen: set[int] = set()
    while parent_id is not None:
        if parent_id == item_id or parent_id in seen:
            raise HTTPException(400, "组织不能移动到自身或其下级组织。")
        seen.add(parent_id)
        parent = active(db, Organization, parent_id)
        if parent.status != 1:
            raise HTTPException(400, "上级组织已停用。")
        parent_id = parent.parent_id


@router.get("/organizations/tree")
def organization_tree(db: Session = Depends(get_db), user: User = Depends(actor)) -> dict:
    items = db.scalars(select(Organization).where(Organization.deleted_at.is_(None)).order_by(
        Organization.name, Organization.id)).all()
    items = [item for item in items if organization_role(db, user, item.id)]
    nodes = {item.id: {**serialize(item), "children": []} for item in items}
    roots = []
    for item in items:
        parent = nodes.get(item.parent_id)
        if parent and parent is not nodes[item.id]:
            parent["children"].append(nodes[item.id])
        else:
            roots.append(nodes[item.id])
    return success_response(roots).model_dump(mode="json")


@router.get("/{kind}")
def list_entities(
    kind: str, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    keyword: str = "", status: int | None = Query(None, ge=0, le=1),
    organization_id: int | None = None, scope: Literal["platform"] | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(actor),
) -> dict:
    spec = spec_for(kind)
    statement = select(spec.model)
    conditions = []
    if hasattr(spec.model, "deleted_at"):
        conditions.append(spec.model.deleted_at.is_(None))
    if keyword.strip():
        term = f"%{keyword.strip()}%"
        searchable = [getattr(spec.model, spec.name).ilike(term)]
        if kind == "users":
            searchable.append(User.email.ilike(term))
        conditions.append(or_(*searchable))
    if status is not None:
        conditions.append(spec.model.status == status)
    if organization_id is not None and kind == "user-groups":
        raise HTTPException(422, "用户组不按组织筛选。")
    if scope is not None:
        if kind != "projects" or organization_id is not None:
            raise HTTPException(422, "项目范围筛选条件无效。")
        conditions.append(Project.organization_id.is_(None))
    if organization_id is not None and hasattr(spec.model, "organization_id"):
        conditions.append(spec.model.organization_id == organization_id)
    if not is_platform_admin(user) and kind != "user-groups":
        accessible = [id_ for id_ in db.scalars(select(Organization.id).where(
            Organization.deleted_at.is_(None), Organization.status == 1))
            if organization_role(db, user, id_)]
        if kind == "users":
            conditions.append(User.id.in_(select(OrganizationMember.user_id).where(
                OrganizationMember.organization_id.in_(accessible))))
        elif kind == "organizations":
            conditions.append(Organization.id.in_(accessible))
        elif kind == "projects":
            own_projects = select(ProjectMember.project_id).where(
                ProjectMember.user_id == user.id, ProjectMember.status == 1)
            active_orgs = select(Organization.id).where(
                Organization.deleted_at.is_(None), Organization.status == 1)
            conditions.append(or_(Project.organization_id.in_(accessible),
                                  (Project.id.in_(own_projects) | (Project.owner_user_id == user.id))
                                  & Project.organization_id.in_(active_orgs),
                                  Project.organization_id.is_(None) & or_(
                                      Project.owner_user_id == user.id, Project.id.in_(own_projects))))
        elif kind != "user-groups":
            conditions.append(spec.model.organization_id.in_(accessible))
    statement = statement.where(*conditions)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    items = db.scalars(statement.order_by(spec.model.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return success_response({
        "items": [serialize(item) for item in items], "page": page,
        "page_size": page_size, "total": total,
    }).model_dump(mode="json")


@router.post("/{kind}", status_code=201)
def create_entity(kind: str, payload: EntityPayload, db: Session = Depends(get_db),
                  user: User = Depends(actor)) -> dict:
    spec = spec_for(kind)
    data = payload.model_dump(exclude_unset=True)
    if any(field not in spec.fields and not (kind == "users" and field == "password") for field in data):
        raise HTTPException(422, "请求包含不适用于此模块的字段。")
    for field in spec.required:
        if not data.get(field) or isinstance(data[field], str) and not data[field].strip():
            raise HTTPException(422, f"{field} 为必填字段。")
    if kind == "projects":
        if data.get("organization_id") is None:
            require_platform(user)
        else:
            validate_org(db, data["organization_id"])
            require_access(db, user, kind, organization_id=data["organization_id"], write=True)
    if kind == "user-groups":
        require_access(db, user, kind, write=True)
    if kind == "organizations":
        validate_parent(db, data.get("parent_id"))
        if data.get("parent_id") is None:
            require_platform(user)
        else:
            require_access(db, user, kind, organization_id=data["parent_id"], write=True)
    if kind == "users":
        require_platform(user)
        data.setdefault("is_platform_admin", 0)
    if kind == "projects":
        data["owner_user_id"] = data.get("owner_user_id") or user.id
        validate_owner(db, data["owner_user_id"])
        if data.get("organization_id") is not None:
            validate_membership(db, data["organization_id"], data["owner_user_id"])
    if kind == "users":
        data["password_hash"] = hash_password(data.pop("password"))
    if kind == "organizations":
        data["owner_user_id"] = user.id
    if kind == "user-groups":
        data["created_by"] = user.id
    if kind in CODE_FIELDS:
        code_field, prefix = CODE_FIELDS[kind]
        code = data.get(code_field)
        data[code_field] = code.strip() if isinstance(code, str) and code.strip() else (
            f"{prefix}_{uuid4().hex}"
        )
    entity = spec.model(**data)
    try:
        db.add(entity)
        db.commit()
        db.refresh(entity)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "编码、用户名或邮箱已存在。") from exc
    return success_response(serialize(entity)).model_dump(mode="json")


@router.get("/{kind}/{entity_id}")
def get_entity(kind: str, entity_id: int, db: Session = Depends(get_db),
               user: User = Depends(actor)) -> dict:
    item = active(db, spec_for(kind).model, entity_id)
    require_access(db, user, kind, item)
    return success_response(serialize(item)).model_dump(mode="json")


@router.patch("/{kind}/{entity_id}")
def update_entity(kind: str, entity_id: int, payload: EntityPayload,
                  db: Session = Depends(get_db), user: User = Depends(actor)) -> dict:
    spec = spec_for(kind)
    item = active(db, spec.model, entity_id)
    require_access(db, user, kind, item, write=True)
    data = payload.model_dump(exclude_unset=True)
    if not data or any(field not in spec.fields for field in data):
        raise HTTPException(422, "请求字段无效。")
    immutable = {"users": ("username",), "user-groups": ("group_code",),
                 "organizations": ("code",), "projects": ("organization_id", "code")}
    if any(field in data for field in immutable[kind]):
        raise HTTPException(422, "编码和归属信息创建后不可修改。")
    if any(value is None for field, value in data.items()
           if not (kind == "organizations" and field == "parent_id")):
        raise HTTPException(422, "请提供有效字段值。")
    if kind == "users":
        next_status = data.get("status", item.status)
        next_is_platform_admin = data.get("is_platform_admin", item.is_platform_admin)
        if item.id == user.id and next_status == 0:
            raise HTTPException(400, "不能停用当前管理员。")
        if item.id == user.id and next_is_platform_admin == 0:
            raise HTTPException(400, "不能移除当前账号的平台管理员权限。")
        if item.status == 1 and item.is_platform_admin == 1 and (next_status != 1 or next_is_platform_admin != 1):
            remaining = db.scalar(select(func.count()).select_from(User).where(
                User.deleted_at.is_(None),
                User.status == 1,
                User.is_platform_admin == 1,
                User.id != item.id,
            )) or 0
            if remaining == 0:
                raise HTTPException(400, "至少需要保留一个启用的平台管理员。")
    if kind == "projects" and "owner_user_id" in data:
        validate_owner(db, data["owner_user_id"])
        if item.organization_id is not None:
            validate_membership(db, item.organization_id, data["owner_user_id"])
    if kind == "organizations":
        if "parent_id" in data:
            validate_parent(db, data["parent_id"], item.id)
            if data["parent_id"] is None:
                require_platform(user)
            else:
                require_access(db, user, kind, organization_id=data["parent_id"], write=True)
        if data.get("status") == 0 and db.scalar(select(Organization.id).where(
            Organization.parent_id == item.id, Organization.status == 1,
            Organization.deleted_at.is_(None)).limit(1)):
            raise HTTPException(409, "请先停用下级组织。")
    for field, value in data.items():
        setattr(item, field, value)
    return save(db, item)


@router.post("/users/{entity_id}/reset-password")
def reset_password(entity_id: int, payload: PasswordReset, db: Session = Depends(get_db),
                   user: User = Depends(actor)) -> dict:
    require_platform(user)
    user = active(db, User, entity_id)
    user.password_hash = hash_password(payload.password)
    db.commit()
    return success_response().model_dump(mode="json")


@router.get("/{kind}/{entity_id}/members")
def list_members(kind: str, entity_id: int, db: Session = Depends(get_db),
                 user: User = Depends(actor)) -> dict:
    if kind not in MEMBERS:
        raise HTTPException(404, "成员模块不存在。")
    item = active(db, spec_for(kind).model, entity_id)
    require_access(db, user, kind, item, write=kind == "user-groups")
    model, parent = MEMBERS[kind]
    rows = db.execute(select(model, User).join(User, model.user_id == User.id).where(
        getattr(model, parent) == entity_id, User.deleted_at.is_(None)).order_by(User.id)).all()
    return success_response([
        {**serialize(user), "role": getattr(member, "role", None), "member_status": getattr(member, "status", 1)}
        for member, user in rows
    ]).model_dump(mode="json")


@router.post("/{kind}/{entity_id}/members", status_code=201)
def add_member(kind: str, entity_id: int, payload: MemberPayload,
               db: Session = Depends(get_db), user: User = Depends(actor)) -> dict:
    if kind not in MEMBERS:
        raise HTTPException(404, "成员模块不存在。")
    parent_item = active(db, spec_for(kind).model, entity_id)
    require_access(db, user, kind, parent_item, write=True)
    validate_owner(db, payload.user_id)
    if kind == "projects" and parent_item.organization_id is not None:
        validate_membership(db, parent_item.organization_id, payload.user_id)
    if kind in ROLES and payload.role not in ROLES[kind]:
        raise HTTPException(422, "成员角色无效。")
    if kind == "user-groups" and payload.role:
        raise HTTPException(422, "用户组成员不设置角色。")
    model, parent = MEMBERS[kind]
    values = {parent: entity_id, "user_id": payload.user_id}
    if kind != "user-groups":
        values.update(role=payload.role, status=payload.status)
    return save(db, model(**values))


@router.patch("/{kind}/{entity_id}/members/{user_id}")
def update_member(kind: str, entity_id: int, user_id: int, payload: MemberUpdate,
                  db: Session = Depends(get_db), user: User = Depends(actor)) -> dict:
    if kind not in ROLES:
        raise HTTPException(404, "成员角色不可编辑。")
    parent_item = active(db, spec_for(kind).model, entity_id)
    require_access(db, user, kind, parent_item, write=True)
    model, parent = MEMBERS[kind]
    member = db.scalar(select(model).where(getattr(model, parent) == entity_id, model.user_id == user_id))
    if not member:
        raise HTTPException(404, "成员不存在。")
    data = payload.model_dump(exclude_unset=True)
    if not data or any(value is None for value in data.values()):
        raise HTTPException(422, "请求字段无效。")
    if "role" in data and data["role"] not in ROLES[kind]:
        raise HTTPException(422, "成员角色无效。")
    for field, value in data.items():
        setattr(member, field, value)
    return save(db, member)


@router.delete("/{kind}/{entity_id}/members/{user_id}")
def remove_member(kind: str, entity_id: int, user_id: int, db: Session = Depends(get_db),
                  user: User = Depends(actor)) -> dict:
    if kind not in MEMBERS:
        raise HTTPException(404, "成员模块不存在。")
    parent_item = active(db, spec_for(kind).model, entity_id)
    require_access(db, user, kind, parent_item, write=True)
    model, parent = MEMBERS[kind]
    member = db.scalar(select(model).where(getattr(model, parent) == entity_id, model.user_id == user_id))
    if not member:
        raise HTTPException(404, "成员不存在。")
    db.delete(member)
    db.commit()
    return success_response().model_dump(mode="json")


@router.get("/users/{entity_id}/organizations")
def user_organizations(entity_id: int, db: Session = Depends(get_db),
                       user: User = Depends(actor)) -> dict:
    if entity_id != user.id:
        require_platform(user)
    active(db, User, entity_id)
    items = db.scalars(select(Organization).join(OrganizationMember).where(
        OrganizationMember.user_id == entity_id, Organization.deleted_at.is_(None))).all()
    return success_response([serialize(item) for item in items]).model_dump(mode="json")
