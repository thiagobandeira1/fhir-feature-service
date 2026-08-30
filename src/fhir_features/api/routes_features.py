"""Feature endpoints: per-patient, bulk paged, the schema contract, and the panel rollup."""

from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from fhir_features.api.deps import get_db, get_valuesets_version
from fhir_features.api.errors import NotFoundError
from fhir_features.api.schemas import (
    FeatureFieldSchema,
    FeaturePageResponse,
    FeatureRowResponse,
    FeatureSchemaResponse,
    PanelSummaryResponse,
)
from fhir_features.features.queries import compute_features, count_patients, panel_summary
from fhir_features.features.registry import AS_OF_SEMANTICS, FEATURE_VERSION, FEATURES
from fhir_features.store.db import Database
from fhir_features.store.read import resolve_patient

router = APIRouter(prefix="/v1", tags=["features"])


def _today() -> date:
    return datetime.now(UTC).date()


@router.get("/patients/{patient_id}/features", response_model=FeatureRowResponse)
def patient_features(
    patient_id: str,
    db: Annotated[Database, Depends(get_db)],
    valuesets_version: Annotated[str, Depends(get_valuesets_version)],
    as_of: Annotated[date | None, Query()] = None,
    source: Annotated[str | None, Query()] = None,
) -> FeatureRowResponse:
    patient = resolve_patient(db, patient_id, source)
    if patient is None:
        raise NotFoundError("patient not found")
    rows = compute_features(db, as_of or _today(), source=patient["source"], patient_id=patient_id)
    return FeatureRowResponse(
        feature_version=FEATURE_VERSION,
        valuesets_version=valuesets_version,
        features=rows[0],
    )


@router.get("/features", response_model=FeaturePageResponse)
def features_page(
    db: Annotated[Database, Depends(get_db)],
    valuesets_version: Annotated[str, Depends(get_valuesets_version)],
    as_of: Annotated[date | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
    source: Annotated[str | None, Query()] = None,
) -> FeaturePageResponse:
    effective_as_of = as_of or _today()
    rows = compute_features(db, effective_as_of, source=source, limit=limit, offset=offset)
    return FeaturePageResponse(
        as_of=effective_as_of,
        feature_version=FEATURE_VERSION,
        valuesets_version=valuesets_version,
        items=rows,
        total=count_patients(db, source=source),
    )


@router.get("/features/schema", response_model=FeatureSchemaResponse)
def features_schema(
    valuesets_version: Annotated[str, Depends(get_valuesets_version)],
) -> FeatureSchemaResponse:
    return FeatureSchemaResponse(
        feature_version=FEATURE_VERSION,
        valuesets_version=valuesets_version,
        as_of_semantics=AS_OF_SEMANTICS,
        features=[
            FeatureFieldSchema(
                name=f.name,
                type=f.type,
                nullable=f.nullable,
                description=f.description,
                value_set_id=f.value_set_id,
                added_in=f.added_in,
            )
            for f in FEATURES
        ],
    )


@router.get("/panel/summary", response_model=PanelSummaryResponse)
def panel(
    db: Annotated[Database, Depends(get_db)],
    as_of: Annotated[date | None, Query()] = None,
) -> PanelSummaryResponse:
    return PanelSummaryResponse(**panel_summary(db, as_of or _today()))
