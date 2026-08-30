"""Pydantic response models — the OpenAPI contract downstream repos pin."""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel

from fhir_features.canonical.models import ParseIssue


class IngestResponse(BaseModel):
    patient_id: str
    source: str
    bundle_hash: str
    action: str
    resource_counts: dict[str, int]
    skipped_resource_types: dict[str, int]
    warnings: list[ParseIssue]


class PatientSummary(BaseModel):
    source: str
    patient_id: str
    birth_date: date | None
    sex: str
    deceased: bool
    last_ingested_at: datetime


class PatientListResponse(BaseModel):
    items: list[PatientSummary]
    total: int


class PatientRecordResponse(BaseModel):
    patient: dict[str, Any]
    conditions: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    procedures: list[dict[str, Any]] = []
    medications: list[dict[str, Any]] = []
    encounters: list[dict[str, Any]] = []
    immunizations: list[dict[str, Any]] = []
    claim_diagnoses: list[dict[str, Any]] = []
    counts: dict[str, int]


class FeatureRowResponse(BaseModel):
    feature_version: str
    valuesets_version: str
    features: dict[str, Any]


class FeaturePageResponse(BaseModel):
    as_of: date
    feature_version: str
    valuesets_version: str
    items: list[dict[str, Any]]
    total: int


class FeatureFieldSchema(BaseModel):
    name: str
    type: str
    nullable: bool
    description: str
    value_set_id: str | None
    added_in: str


class FeatureSchemaResponse(BaseModel):
    feature_version: str
    valuesets_version: str
    as_of_semantics: str
    features: list[FeatureFieldSchema]


class PanelSummaryResponse(BaseModel):
    as_of: date
    patient_count: int
    avg_age: float | None
    pct_female: float | None
    prevalence: dict[str, float | None]
    tobacco_unscreened_count: int
    encounters_365d_total: int
    ed_visits_365d_total: int
    inpatient_admits_365d_total: int


class HealthResponse(BaseModel):
    status: str
    service_version: str
    schema_version: int
    feature_version: str
