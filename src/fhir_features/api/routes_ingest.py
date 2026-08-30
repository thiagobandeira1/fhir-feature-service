"""POST /v1/ingest/bundle — idempotent single-bundle ingestion."""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

import fhir_features
from fhir_features.adapters.synthea import record_set_from_bundle
from fhir_features.api.deps import get_db
from fhir_features.api.errors import problem_response
from fhir_features.api.schemas import IngestResponse
from fhir_features.config import get_settings
from fhir_features.fhir.bundle import canonical_bundle_hash
from fhir_features.store.db import Database
from fhir_features.store.loader import bundle_already_loaded, load_patient

router = APIRouter(prefix="/v1/ingest", tags=["ingest"])


@router.post(
    "/bundle",
    response_model=IngestResponse,
    responses={413: {"description": "Bundle over size cap"}, 422: {"description": "Invalid"}},
)
async def ingest_bundle(
    request: Request, db: Annotated[Database, Depends(get_db)]
) -> IngestResponse | JSONResponse:
    body = await request.body()
    max_bytes = get_settings().max_bundle_bytes
    if len(body) > max_bytes:
        return problem_response(
            413,
            "Bundle too large",
            f"bundle exceeds the configured cap of {max_bytes} bytes",
            code="bundle_too_large",
        )
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return problem_response(
            422,
            "Bundle validation failed",
            "request body is not valid JSON",
            code="invalid_json",
        )

    record_set = record_set_from_bundle(payload)  # raises BundleValidationError -> 422
    bundle_hash = canonical_bundle_hash(payload)

    if bundle_already_loaded(db, bundle_hash):
        return IngestResponse(
            patient_id=record_set.patient.patient_id,
            source=record_set.source,
            bundle_hash=bundle_hash,
            action="unchanged",
            resource_counts={},
            skipped_resource_types=record_set.skipped,
            warnings=record_set.warnings,
        )

    result = load_patient(
        db,
        record_set,
        bundle_hash=bundle_hash,
        raw_payload=json.dumps(payload, separators=(",", ":")),
        service_version=fhir_features.__version__,
    )
    return IngestResponse(
        patient_id=result.patient_id,
        source=result.source,
        bundle_hash=bundle_hash,
        action=result.action,
        resource_counts=result.row_counts,
        skipped_resource_types=record_set.skipped,
        warnings=record_set.warnings,
    )
