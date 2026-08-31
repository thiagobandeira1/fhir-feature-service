"""GET /healthz — liveness, readiness, and the version handshake in one."""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

import fhir_features
from fhir_features.api.deps import get_db
from fhir_features.api.errors import problem_response
from fhir_features.api.schemas import HealthResponse
from fhir_features.features.registry import FEATURE_VERSION
from fhir_features.store.db import Database

router = APIRouter(tags=["ops"])


@router.get(
    "/healthz", response_model=HealthResponse, responses={503: {"description": "Not ready"}}
)
def healthz(db: Annotated[Database, Depends(get_db)]) -> HealthResponse | JSONResponse:
    try:
        with db.reader() as conn:
            row = conn.execute("SELECT max(version) FROM schema_migrations").fetchone()
        schema_version = int(row[0]) if row and row[0] is not None else 0
    except Exception:
        return problem_response(503, "Not ready", "database is unavailable", code="db_unavailable")
    if schema_version < 3:
        return problem_response(503, "Not ready", "migrations not current", code="migrations_stale")
    return HealthResponse(
        status="ok",
        service_version=fhir_features.__version__,
        schema_version=schema_version,
        feature_version=FEATURE_VERSION,
    )
