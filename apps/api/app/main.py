"""FastAPI application factory."""

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.v1 import (
    agents,
    analytics,
    auth,
    health,
    integrations,
    intelligence,
    leads,
    organizations,
    outreach,
    pipeline,
    workflows,
)
from app.core.config import Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.middleware import RequestContextMiddleware
from app.observability.logging import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.validate_for_runtime()
    configure_logging(settings.log_level, settings.service_name, settings.log_json)

    app = FastAPI(
        title="SalesIQ API",
        version=__version__,
        openapi_url="/api/v1/openapi.json",
        docs_url=None if settings.is_production else "/api/docs",
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["content-type", "x-request-id", "x-csrf-token", "idempotency-key"],
        expose_headers=["x-request-id"],
    )
    # Added last so it is the outermost layer and every response carries a request ID.
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)

    v1 = APIRouter(prefix="/api/v1")
    v1.include_router(health.router)
    v1.include_router(auth.router)
    v1.include_router(organizations.router)
    v1.include_router(leads.router)
    v1.include_router(pipeline.router)
    v1.include_router(intelligence.router)
    v1.include_router(workflows.router)
    v1.include_router(agents.router)
    v1.include_router(outreach.router)
    v1.include_router(analytics.router)
    v1.include_router(integrations.router)
    v1.include_router(integrations.public_router)
    v1.include_router(outreach.public_router)
    app.include_router(v1)
    return app


app = create_app()
