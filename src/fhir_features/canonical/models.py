"""Frozen pydantic row models — the canonical intermediate representation (CIR).

Each row model mirrors one canonical table one-to-one (``source`` and ``ingested_at`` are added
by the loader). ``PatientRecordSet`` is the adapter unit of work: one fully extracted patient.
See ADR-0003.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from fhir_features.canonical.codes import EncounterClass
from fhir_features.canonical.dates import DatePrecision


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class ParseIssue(_FrozenModel):
    """A non-fatal extraction problem: an issue code and a JSON pointer — never values."""

    code: str
    json_pointer: str


class PatientRow(_FrozenModel):
    patient_id: str
    birth_date: date | None
    death_date: date | None = None
    sex: Literal["male", "female", "other", "unknown"] = "unknown"
    race: str | None = None
    ethnicity: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None


class EncounterRow(_FrozenModel):
    encounter_id: str
    patient_id: str
    encounter_class: EncounterClass
    type_code: str | None = None
    type_system: str | None = None
    type_display: str | None = None
    start_ts: datetime | None
    end_ts: datetime | None = None
    start_date: date
    date_precision: DatePrecision


class ConditionRow(_FrozenModel):
    condition_id: str
    patient_id: str
    encounter_id: str | None = None
    code: str
    code_system: str
    code_display: str | None = None
    clinical_status: str | None = None
    verification_status: str | None = None
    onset_date: date
    abatement_date: date | None = None
    recorded_date: date | None = None
    date_precision: DatePrecision


class ObservationRow(_FrozenModel):
    observation_id: str
    parent_observation_id: str | None = None
    patient_id: str
    encounter_id: str | None = None
    code: str
    code_system: str
    code_display: str | None = None
    category: str | None = None
    effective_ts: datetime | None
    effective_date: date
    date_precision: DatePrecision
    value_num: float | None = None
    value_unit: str | None = None
    value_code: str | None = None
    value_code_system: str | None = None
    value_text: str | None = None
    status: str


class ProcedureRow(_FrozenModel):
    procedure_id: str
    patient_id: str
    encounter_id: str | None = None
    code: str
    code_system: str
    code_display: str | None = None
    performed_date: date
    performed_end_date: date | None = None
    date_precision: DatePrecision
    status: str


class MedicationRequestRow(_FrozenModel):
    medication_request_id: str
    patient_id: str
    encounter_id: str | None = None
    code: str
    code_system: str
    code_display: str | None = None
    authored_date: date
    date_precision: DatePrecision
    status: str | None = None
    intent: str | None = None


class ImmunizationRow(_FrozenModel):
    immunization_id: str
    patient_id: str
    code: str
    code_system: str
    code_display: str | None = None
    occurrence_date: date


class ClaimDiagnosisRow(_FrozenModel):
    claim_id: str
    diagnosis_sequence: int
    patient_id: str
    claim_type: str | None = None
    billable_period_start: date | None = None
    billable_period_end: date | None = None
    diagnosis_code: str
    diagnosis_code_system: str
    diagnosis_display: str | None = None
    resolved_condition_id: str


class CodingRow(_FrozenModel):
    """One coding of a Condition/Procedure — every coding preserved, raw URI included."""

    resource_type: Literal["Condition", "Procedure"]
    resource_id: str
    coding_seq: int
    code: str
    code_system_uri: str | None
    code_system: str
    display: str | None = None


class PatientRecordSet(_FrozenModel):
    """One fully extracted patient: the unit an adapter yields and the loader persists."""

    source: str
    patient: PatientRow
    encounters: list[EncounterRow] = []
    conditions: list[ConditionRow] = []
    observations: list[ObservationRow] = []
    procedures: list[ProcedureRow] = []
    medication_requests: list[MedicationRequestRow] = []
    immunizations: list[ImmunizationRow] = []
    claim_diagnoses: list[ClaimDiagnosisRow] = []
    codings: list[CodingRow] = []
    skipped: dict[str, int] = {}
    warnings: list[ParseIssue] = []
