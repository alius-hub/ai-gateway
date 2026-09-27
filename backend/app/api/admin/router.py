from fastapi import APIRouter

from app.modules.audit.router import router as audit_router
from app.modules.audit.settings import router as log_settings_router
from app.modules.auth.router import router as auth_router
from app.modules.credential.router import router as credential_router
from app.modules.identity.router import router as identity_router
from app.modules.model.playground import router as playground_router
from app.modules.model.playground_history import router as playground_history_router
from app.modules.model.router import router as model_router
from app.modules.overview.router import router as overview_router
from app.modules.provider.router import router as provider_router
from app.modules.routing.router import router as routing_router

admin_router = APIRouter()
admin_router.include_router(auth_router)
admin_router.include_router(overview_router)
admin_router.include_router(credential_router)
admin_router.include_router(provider_router)
admin_router.include_router(model_router)
admin_router.include_router(playground_router)
admin_router.include_router(playground_history_router)
admin_router.include_router(routing_router)
admin_router.include_router(audit_router)
admin_router.include_router(log_settings_router)
admin_router.include_router(identity_router)
