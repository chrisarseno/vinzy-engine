"""FastAPI application factory for Vinzy-Engine."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from vinzy_engine.common.config import get_settings
from vinzy_engine.common.schemas import HealthResponse


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup
        from vinzy_engine.deps import get_db
        db = get_db()
        await db.init()
        await db.create_all()
        yield
        # Shutdown
        await db.close()

    app = FastAPI(
        title=settings.api_title,
        version=settings.api_version,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", response_model=HealthResponse)
    async def health():
        return HealthResponse(version=settings.api_version)

    # Mount routers
    from vinzy_engine.licensing.router import router as licensing_router
    from vinzy_engine.activation.router import router as activation_router
    from vinzy_engine.usage.router import router as usage_router
    from vinzy_engine.tenants.router import router as tenant_router
    from vinzy_engine.audit.router import router as audit_router
    from vinzy_engine.anomaly.router import router as anomaly_router
    from vinzy_engine.webhooks.router import router as webhook_router
    from vinzy_engine.provisioning.router import router as provisioning_router

    prefix = settings.api_prefix
    app.include_router(licensing_router, prefix=prefix, tags=["licensing"])
    app.include_router(activation_router, prefix=prefix, tags=["activation"])
    app.include_router(usage_router, prefix=prefix, tags=["usage"])
    app.include_router(tenant_router, prefix=prefix, tags=["tenants"])
    app.include_router(audit_router, prefix=prefix, tags=["audit"])
    app.include_router(anomaly_router, prefix=prefix, tags=["anomaly"])
    app.include_router(webhook_router, prefix=prefix, tags=["webhooks"])
    app.include_router(provisioning_router, prefix=prefix, tags=["provisioning"])

    # Mount dashboard sub-application
    from vinzy_engine.dashboard.router import create_dashboard_app
    app.mount("/dashboard", create_dashboard_app())

    return app
