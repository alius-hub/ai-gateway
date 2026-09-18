from fastapi import APIRouter

from app.modules.audit.router import router as audit_router
from app.modules.auth.router import router as auth_router
from app.modules.credential.router import router as credential_router
from app.modules.model.router import router as model_router
from app.modules.node.router import router as node_router
from app.modules.organization.router import router as organization_router
from app.modules.overview.router import router as overview_router
from app.modules.project.router import router as project_router
from app.modules.provider.router import router as provider_router
from app.modules.routing.router import router as routing_router

admin_router = APIRouter()
admin_router.include_router(auth_router)
admin_router.include_router(overview_router)
admin_router.include_router(organization_router)
admin_router.include_router(project_router)
admin_router.include_router(credential_router)
admin_router.include_router(provider_router)
admin_router.include_router(model_router)
admin_router.include_router(node_router)
admin_router.include_router(routing_router)
admin_router.include_router(audit_router)
