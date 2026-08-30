"""GET /v1/patients and the event-level /record contract (P1, P4)."""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from fhir_features.api.deps import get_db
from fhir_features.api.errors import NotFoundError, problem_response
from fhir_features.api.schemas import PatientListResponse, PatientRecordResponse, PatientSummary
from fhir_features.store.db import Database
from fhir_features.store.read import (
    RECORD_SECTIONS,
    get_record_sections,
    list_patients,
    resolve_patient,
)

router = APIRouter(prefix="/v1/patients", tags=["patients"])


@router.get("", response_model=PatientListResponse)
def patients_index(
    db: Annotated[Database, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    source: Annotated[str | None, Query()] = None,
) -> PatientListResponse:
    page = list_patients(db, limit=limit, offset=offset, source=source)
    return PatientListResponse(
        items=[PatientSummary(**item) for item in page.items], total=page.total
    )


@router.get(
    "/{patient_id}/record",
    response_model=PatientRecordResponse,
    response_model_exclude_none=False,
)
def patient_record(
    patient_id: str,
    db: Annotated[Database, Depends(get_db)],
    sections: Annotated[str | None, Query(description="csv subset of sections")] = None,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    observation_codes: Annotated[str | None, Query(description="csv LOINC filter")] = None,
    source: Annotated[str | None, Query()] = None,
) -> PatientRecordResponse | Any:
    requested = (
        [s.strip() for s in sections.split(",") if s.strip()] if sections else list(RECORD_SECTIONS)
    )
    unknown = [s for s in requested if s not in RECORD_SECTIONS]
    if unknown:
        return problem_response(
            422,
            "Request validation failed",
            f"unknown sections: {', '.join(sorted(unknown))}",
            code="unknown_section",
        )
    patient = resolve_patient(db, patient_id, source)
    if patient is None:
        raise NotFoundError("patient not found")
    section_data = get_record_sections(
        db,
        source=patient["source"],
        patient_id=patient_id,
        sections=requested,
        date_from=date_from,
        date_to=date_to,
        observation_codes=(
            [c.strip() for c in observation_codes.split(",") if c.strip()]
            if observation_codes
            else None
        ),
    )
    patient.pop("ingested_at", None)
    return PatientRecordResponse(
        patient=patient,
        counts={name: len(rows) for name, rows in section_data.items()},
        **section_data,
    )
