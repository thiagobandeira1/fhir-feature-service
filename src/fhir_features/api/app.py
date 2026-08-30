"""Application factory: DB lifecycle, migrations, value sets, logging, routes."""

import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response

import fhir_features
from fhir_features.api import routes_features, routes_health, routes_ingest, routes_patients
from fhir_features.api.errors import register_error_handlers
from fhir_features.config import Settings, get_settings
from fhir_features.features.value_sets import load_value_sets
from fhir_features.logging_setup import configure_logging, get_logger
from fhir_features.store.db import Database
from fhir_features.store.migrate import migrate
from fhir_features.store.reference import sync_value_sets

log = get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    configure_logging()
    resolved = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = Database(resolved.db_path)
        schema_version = migrate(db)
        bundle = load_value_sets()
        sync_value_sets(db, bundle)
        app.state.db = db
        app.state.valuesets_version = bundle.version
        log.info(
            "service_started",
            service_version=fhir_features.__version__,
            schema_version=schema_version,
            valuesets_version=bundle.version,
        )
        yield
        db.close()

    app = FastAPI(
        title="fhir-feature-service",
        version=fhir_features.__version__,
        description=(
            "Ingests FHIR R4 bundles (Synthea) into canonical clinical-event tables and serves "
            "leakage-free, as_of-parameterized patient features for value-based-care analytics. "
            "Synthetic data only in this deployment."
        ),
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def access_log(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = str(uuid.uuid4())
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
        log.info(
            "request",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        response.headers["x-request-id"] = request_id
        return response

    register_error_handlers(app)
    app.include_router(routes_ingest.router)
    app.include_router(routes_patients.router)
    app.include_router(routes_features.router)
    app.include_router(routes_health.router)
    return app
