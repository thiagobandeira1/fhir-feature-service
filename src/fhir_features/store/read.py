"""Read-side queries for the API: rosters and the event-level patient record."""

from dataclasses import dataclass
from datetime import date
from typing import Any

from fhir_features.store.db import Database

#: section name -> (table, event-date column, deterministic id columns)
RECORD_SECTIONS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "conditions": ("conditions", "onset_date", ("condition_id",)),
    "observations": ("observations", "effective_date", ("observation_id",)),
    "procedures": ("procedures", "performed_date", ("procedure_id",)),
    "medications": ("medication_requests", "authored_date", ("medication_request_id",)),
    "encounters": ("encounters", "start_date", ("encounter_id",)),
    "immunizations": ("immunizations", "occurrence_date", ("immunization_id",)),
    "claim_diagnoses": (
        "claim_diagnoses",
        "billable_period_start",
        ("claim_id", "diagnosis_sequence"),
    ),
}


class AmbiguousPatientError(LookupError):
    """The patient id exists under more than one source; the caller must disambiguate."""


def _rows_to_dicts(cursor: Any) -> list[dict[str, Any]]:
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def resolve_patient(
    db: Database, patient_id: str, source: str | None
) -> dict[str, Any] | None:
    """Find one patient row; raise :class:`AmbiguousPatientError` on a cross-source clash."""
    sql = "SELECT * FROM patients WHERE patient_id = ?"
    params: list[Any] = [patient_id]
    if source is not None:
        sql += " AND source = ?"
        params.append(source)
    rows = _rows_to_dicts(db.conn.execute(sql, params))
    if not rows:
        return None
    if len(rows) > 1:
        raise AmbiguousPatientError(patient_id)
    return rows[0]


@dataclass(frozen=True)
class PatientPage:
    items: list[dict[str, Any]]
    total: int


def list_patients(
    db: Database, *, limit: int, offset: int, source: str | None
) -> PatientPage:
    where = "" if source is None else " WHERE source = ?"
    params: list[Any] = [] if source is None else [source]
    total_row = db.conn.execute(
        f"SELECT count(*) FROM patients{where}",  # noqa: S608
        params,
    ).fetchone()
    items = _rows_to_dicts(
        db.conn.execute(
            "SELECT source, patient_id, birth_date, sex, "  # noqa: S608
            "(death_date IS NOT NULL) AS deceased, ingested_at AS last_ingested_at "
            f"FROM patients{where} ORDER BY source, patient_id LIMIT ? OFFSET ?",
            [*params, limit, offset],
        )
    )
    return PatientPage(items=items, total=int(total_row[0]) if total_row else 0)


def get_record_sections(
    db: Database,
    *,
    source: str,
    patient_id: str,
    sections: list[str],
    date_from: date | None,
    date_to: date | None,
    observation_codes: list[str] | None,
) -> dict[str, list[dict[str, Any]]]:
    """Fetch the requested sections, each ordered by (event date, id...) ascending."""
    out: dict[str, list[dict[str, Any]]] = {}
    for section in sections:
        table, date_col, id_cols = RECORD_SECTIONS[section]
        sql = f"SELECT * FROM {table} WHERE source = ? AND patient_id = ?"  # noqa: S608
        params: list[Any] = [source, patient_id]
        if date_from is not None:
            sql += f" AND {date_col} >= ?"
            params.append(date_from)
        if date_to is not None:
            sql += f" AND {date_col} <= ?"
            params.append(date_to)
        if section == "observations" and observation_codes:
            placeholders = ", ".join("?" for _ in observation_codes)
            sql += f" AND code IN ({placeholders})"
            params.extend(observation_codes)
        sql += f" ORDER BY {date_col} NULLS FIRST, {', '.join(id_cols)}"
        rows = _rows_to_dicts(db.conn.execute(sql, params))
        for row in rows:
            row.pop("ingested_at", None)
        out[section] = rows
    return out
