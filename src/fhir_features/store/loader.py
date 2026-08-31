"""Transactional per-patient loading (ADR-0004).

Replace-by-patient (DELETE all rows for ``(source, patient_id)``, then INSERT) handles resource
deletion and re-keying for free — row-level upserts would leave orphans. The whole replace plus
its audit row commits atomically; a failed parse or insert rolls back to the previous state, so
partially loaded patients cannot exist.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from fhir_features.canonical.models import PatientRecordSet
from fhir_features.logging_setup import get_logger
from fhir_features.store.db import Database

log = get_logger(__name__)

LoadAction = Literal["created", "replaced", "unchanged", "reparsed"]


def _naive_utc(value: datetime | None) -> datetime | None:
    """Normalize to naive UTC before hitting a TIMESTAMP column.

    duckdb converts tz-aware datetimes through the session timezone; storing naive UTC makes
    the stored value (and every date cast derived from it) machine-independent.
    """
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


_CANONICAL_TABLES = (
    "patients",
    "encounters",
    "conditions",
    "observations",
    "procedures",
    "medication_requests",
    "immunizations",
    "claim_diagnoses",
)


@dataclass(frozen=True)
class LoadResult:
    action: LoadAction
    patient_id: str
    source: str
    row_counts: dict[str, int]


def bundle_already_loaded(db: Database, bundle_hash: str) -> bool:
    """True when this exact bundle content is already the stored state (no-op path)."""
    with db.reader() as conn:
        row = conn.execute(
            "SELECT 1 FROM raw_bundles WHERE bundle_hash = ?", [bundle_hash]
        ).fetchone()
    return row is not None


def _insert_rows(
    conn: Any, table: str, columns: tuple[str, ...], rows: list[tuple[Any, ...]]
) -> None:
    if not rows:
        return
    placeholders = ", ".join("?" for _ in columns)
    conn.executemany(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",  # noqa: S608
        rows,
    )


def load_patient(
    db: Database,
    record_set: PatientRecordSet,
    *,
    bundle_hash: str | None,
    raw_payload: str | None,
    service_version: str,
    reparse: bool = False,
) -> LoadResult:
    """Atomically replace one patient's rows with the record set's contents."""
    source = record_set.source
    patient = record_set.patient
    now = datetime.now(UTC).replace(tzinfo=None)  # stored naive-UTC, machine-independent
    started_at = now

    with db.transaction() as conn:
        existed = (
            conn.execute(
                "SELECT 1 FROM patients WHERE source = ? AND patient_id = ?",
                [source, patient.patient_id],
            ).fetchone()
            is not None
        )
        action: LoadAction = "reparsed" if reparse else ("replaced" if existed else "created")

        # Codings first: their delete resolves resource ids through the still-present
        # conditions/procedures rows. Scoped by resource_type — a Condition and a Procedure
        # belonging to DIFFERENT patients may share an id value.
        conn.execute(
            "DELETE FROM resource_codings WHERE source = ? AND resource_type = 'Condition' "
            "AND resource_id IN "
            "(SELECT condition_id FROM conditions WHERE source = ? AND patient_id = ?)",
            [source, source, patient.patient_id],
        )
        conn.execute(
            "DELETE FROM resource_codings WHERE source = ? AND resource_type = 'Procedure' "
            "AND resource_id IN "
            "(SELECT procedure_id FROM procedures WHERE source = ? AND patient_id = ?)",
            [source, source, patient.patient_id],
        )
        for table in _CANONICAL_TABLES:
            conn.execute(
                f"DELETE FROM {table} WHERE source = ? AND patient_id = ?",  # noqa: S608
                [source, patient.patient_id],
            )

        _insert_rows(
            conn,
            "patients",
            (
                "source",
                "patient_id",
                "birth_date",
                "death_date",
                "sex",
                "race",
                "ethnicity",
                "city",
                "state",
                "postal_code",
                "ingested_at",
            ),
            [
                (
                    source,
                    patient.patient_id,
                    patient.birth_date,
                    patient.death_date,
                    patient.sex,
                    patient.race,
                    patient.ethnicity,
                    patient.city,
                    patient.state,
                    patient.postal_code,
                    now,
                )
            ],
        )
        _insert_rows(
            conn,
            "encounters",
            (
                "source",
                "encounter_id",
                "patient_id",
                "encounter_class",
                "type_code",
                "type_system",
                "type_display",
                "start_ts",
                "end_ts",
                "start_date",
                "date_precision",
                "ingested_at",
            ),
            [
                (
                    source,
                    e.encounter_id,
                    e.patient_id,
                    e.encounter_class,
                    e.type_code,
                    e.type_system,
                    e.type_display,
                    _naive_utc(e.start_ts),
                    _naive_utc(e.end_ts),
                    e.start_date,
                    e.date_precision,
                    now,
                )
                for e in record_set.encounters
            ],
        )
        _insert_rows(
            conn,
            "conditions",
            (
                "source",
                "condition_id",
                "patient_id",
                "encounter_id",
                "code",
                "code_system",
                "code_display",
                "clinical_status",
                "verification_status",
                "onset_date",
                "abatement_date",
                "recorded_date",
                "date_precision",
                "ingested_at",
            ),
            [
                (
                    source,
                    c.condition_id,
                    c.patient_id,
                    c.encounter_id,
                    c.code,
                    c.code_system,
                    c.code_display,
                    c.clinical_status,
                    c.verification_status,
                    c.onset_date,
                    c.abatement_date,
                    c.recorded_date,
                    c.date_precision,
                    now,
                )
                for c in record_set.conditions
            ],
        )
        _insert_rows(
            conn,
            "observations",
            (
                "source",
                "observation_id",
                "parent_observation_id",
                "patient_id",
                "encounter_id",
                "code",
                "code_system",
                "code_display",
                "category",
                "effective_ts",
                "effective_date",
                "date_precision",
                "value_num",
                "value_unit",
                "value_code",
                "value_code_system",
                "value_text",
                "status",
                "ingested_at",
            ),
            [
                (
                    source,
                    o.observation_id,
                    o.parent_observation_id,
                    o.patient_id,
                    o.encounter_id,
                    o.code,
                    o.code_system,
                    o.code_display,
                    o.category,
                    _naive_utc(o.effective_ts),
                    o.effective_date,
                    o.date_precision,
                    o.value_num,
                    o.value_unit,
                    o.value_code,
                    o.value_code_system,
                    o.value_text,
                    o.status,
                    now,
                )
                for o in record_set.observations
            ],
        )
        _insert_rows(
            conn,
            "procedures",
            (
                "source",
                "procedure_id",
                "patient_id",
                "encounter_id",
                "code",
                "code_system",
                "code_display",
                "performed_date",
                "performed_end_date",
                "date_precision",
                "status",
                "ingested_at",
            ),
            [
                (
                    source,
                    p.procedure_id,
                    p.patient_id,
                    p.encounter_id,
                    p.code,
                    p.code_system,
                    p.code_display,
                    p.performed_date,
                    p.performed_end_date,
                    p.date_precision,
                    p.status,
                    now,
                )
                for p in record_set.procedures
            ],
        )
        _insert_rows(
            conn,
            "medication_requests",
            (
                "source",
                "medication_request_id",
                "patient_id",
                "encounter_id",
                "code",
                "code_system",
                "code_display",
                "authored_date",
                "date_precision",
                "status",
                "intent",
                "ingested_at",
            ),
            [
                (
                    source,
                    m.medication_request_id,
                    m.patient_id,
                    m.encounter_id,
                    m.code,
                    m.code_system,
                    m.code_display,
                    m.authored_date,
                    m.date_precision,
                    m.status,
                    m.intent,
                    now,
                )
                for m in record_set.medication_requests
            ],
        )
        _insert_rows(
            conn,
            "immunizations",
            (
                "source",
                "immunization_id",
                "patient_id",
                "code",
                "code_system",
                "code_display",
                "occurrence_date",
                "ingested_at",
            ),
            [
                (
                    source,
                    i.immunization_id,
                    i.patient_id,
                    i.code,
                    i.code_system,
                    i.code_display,
                    i.occurrence_date,
                    now,
                )
                for i in record_set.immunizations
            ],
        )
        _insert_rows(
            conn,
            "claim_diagnoses",
            (
                "source",
                "claim_id",
                "diagnosis_sequence",
                "patient_id",
                "claim_type",
                "billable_period_start",
                "billable_period_end",
                "diagnosis_code",
                "diagnosis_code_system",
                "diagnosis_display",
                "resolved_condition_id",
                "ingested_at",
            ),
            [
                (
                    source,
                    d.claim_id,
                    d.diagnosis_sequence,
                    d.patient_id,
                    d.claim_type,
                    d.billable_period_start,
                    d.billable_period_end,
                    d.diagnosis_code,
                    d.diagnosis_code_system,
                    d.diagnosis_display,
                    d.resolved_condition_id,
                    now,
                )
                for d in record_set.claim_diagnoses
            ],
        )
        _insert_rows(
            conn,
            "resource_codings",
            (
                "source",
                "resource_type",
                "resource_id",
                "coding_seq",
                "code",
                "code_system_uri",
                "code_system",
                "display",
            ),
            [
                (
                    source,
                    c.resource_type,
                    c.resource_id,
                    c.coding_seq,
                    c.code,
                    c.code_system_uri,
                    c.code_system,
                    c.display,
                )
                for c in record_set.codings
            ],
        )

        if bundle_hash is not None and raw_payload is not None:
            conn.execute(
                "DELETE FROM raw_bundles WHERE source = ? AND patient_id = ?",
                [source, patient.patient_id],
            )
            conn.execute(
                "INSERT INTO raw_bundles VALUES (?, ?, ?, ?, ?, ?)",
                [
                    bundle_hash,
                    source,
                    patient.patient_id,
                    sum(_counts(record_set).values()),
                    raw_payload,
                    now,
                ],
            )

        row_counts = _counts(record_set)
        conn.execute(
            "INSERT INTO ingest_log VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                str(uuid.uuid4()),
                source,
                patient.patient_id,
                bundle_hash,
                action,
                json.dumps({"rows": row_counts, "skipped": record_set.skipped}),
                json.dumps([issue.model_dump() for issue in record_set.warnings]),
                started_at,
                datetime.now(UTC),
                service_version,
            ],
        )

    log.info(
        "patient_loaded",
        source=source,
        action=action,
        bundle_hash=bundle_hash,
        row_counts=row_counts,
        warning_count=len(record_set.warnings),
    )
    return LoadResult(
        action=action, patient_id=patient.patient_id, source=source, row_counts=row_counts
    )


def record_failed_ingest(
    db: Database, *, source: str, bundle_hash: str | None, error_code: str, service_version: str
) -> None:
    """Append a failed-ingest audit row (no patient rows are touched on failure)."""
    now = datetime.now(UTC).replace(tzinfo=None)
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO ingest_log VALUES (?, ?, NULL, ?, 'failed', NULL, ?, ?, ?, ?)",
            [
                str(uuid.uuid4()),
                source,
                bundle_hash,
                json.dumps([{"code": error_code, "json_pointer": ""}]),
                now,
                now,
                service_version,
            ],
        )


def _counts(record_set: PatientRecordSet) -> dict[str, int]:
    return {
        "patients": 1,
        "encounters": len(record_set.encounters),
        "conditions": len(record_set.conditions),
        "observations": len(record_set.observations),
        "procedures": len(record_set.procedures),
        "medication_requests": len(record_set.medication_requests),
        "immunizations": len(record_set.immunizations),
        "claim_diagnoses": len(record_set.claim_diagnoses),
        "resource_codings": len(record_set.codings),
    }
