import asyncio
from contextlib import asynccontextmanager, suppress

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin.router import admin_router
from app.api.gateway.router import gateway_router
from app.core.config import get_settings
from app.modules.gateway.archive import CallArchiveMiddleware, archive_worker
from app.schemas.common import HealthCheckResponse

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    worker = asyncio.create_task(archive_worker()) if settings.log_archive_enabled else None
    try:
        yield
    finally:
        if worker:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker


def create_application() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        lifespan=lifespan,
        version="0.1.0",
        description="Enterprise AI Gateway for management and runtime traffic.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(CallArchiveMiddleware)

    @app.get("/health", tags=["System"], response_model=HealthCheckResponse)
    async def health_check() -> HealthCheckResponse:
        return HealthCheckResponse()

    app.include_router(admin_router, prefix=settings.admin_api_prefix)
    app.include_router(gateway_router, prefix=settings.gateway_api_prefix)
    return app


app = create_application()


def start() -> None:
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.app_port,
        reload=settings.debug,
    )
