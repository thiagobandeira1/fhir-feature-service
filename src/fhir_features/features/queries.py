"""Query-time feature computation and the panel rollup."""

from datetime import date
from decimal import Decimal
from functools import lru_cache
from importlib import resources
from typing import Any

from fhir_features.store.db import Database


@lru_cache(maxsize=1)
def _feature_sql() -> str:
    return (
        resources.files("fhir_features.features") / "sql" / "patient_features_v1.sql"
    ).read_text(encoding="utf-8")


def _jsonable(value: Any) -> Any:
    # DECIMAL columns must serialize as JSON numbers (the schema declares 'number'),
    # not as strings the way pydantic renders Decimal by default.
    return float(value) if isinstance(value, Decimal) else value


def _rows_to_dicts(cursor: Any) -> list[dict[str, Any]]:
    columns = [d[0] for d in cursor.description]
    return [
        {col: _jsonable(v) for col, v in zip(columns, row, strict=True)}
        for row in cursor.fetchall()
    ]


def compute_features(
    db: Database,
    as_of: date,
    *,
    source: str | None = None,
    patient_id: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Feature rows at ``as_of``, deterministically ordered by (source, patient_id)."""
    sql = f"SELECT * FROM ({_feature_sql()}) f"  # noqa: S608 — package SQL, not user input
    params: list[Any] = [as_of]
    clauses: list[str] = []
    if source is not None:
        clauses.append("f.source = ?")
        params.append(source)
    if patient_id is not None:
        clauses.append("f.patient_id = ?")
        params.append(patient_id)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY f.source, f.patient_id"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
    with db.reader() as conn:
        return _rows_to_dicts(conn.execute(sql, params))


def count_patients(db: Database, *, source: str | None = None) -> int:
    sql = "SELECT count(*) FROM patients"
    params: list[Any] = []
    if source is not None:
        sql += " WHERE source = ?"
        params.append(source)
    with db.reader() as conn:
        row = conn.execute(sql, params).fetchone()
    return int(row[0]) if row else 0


def panel_summary(db: Database, as_of: date) -> dict[str, Any]:
    """P7's fixed rollup, computed on the fly over the living panel at ``as_of``."""
    sql = f"""
        SELECT
            count(*)                                    AS patient_count,
            round(avg(age_years), 1)                    AS avg_age,
            round(avg(CASE WHEN sex = 'female' THEN 1.0 ELSE 0.0 END), 3) AS pct_female,
            round(avg(has_diabetes::INT), 3)            AS diabetes,
            round(avg(has_hypertension::INT), 3)        AS hypertension,
            round(avg(has_ascvd::INT), 3)               AS ascvd,
            round(avg(has_ckd::INT), 3)                 AS ckd,
            round(avg(has_chf::INT), 3)                 AS chf,
            round(avg(has_copd::INT), 3)                AS copd,
            count(*) FILTER (WHERE tobacco_status_code IS NULL) AS tobacco_unscreened_count,
            coalesce(sum(encounters_365d), 0)           AS encounters_365d_total,
            coalesce(sum(ed_visits_365d), 0)            AS ed_visits_365d_total,
            coalesce(sum(inpatient_admits_365d), 0)     AS inpatient_admits_365d_total
        FROM ({_feature_sql()}) f
        WHERE NOT f.is_deceased
    """  # noqa: S608 — package SQL, not user input
    with db.reader() as conn:
        rows = _rows_to_dicts(conn.execute(sql, [as_of]))
    row = rows[0]
    return {
        "as_of": as_of,
        "patient_count": row["patient_count"],
        "avg_age": row["avg_age"],
        "pct_female": row["pct_female"],
        "prevalence": {
            "diabetes": row["diabetes"],
            "hypertension": row["hypertension"],
            "ascvd": row["ascvd"],
            "ckd": row["ckd"],
            "chf": row["chf"],
            "copd": row["copd"],
        },
        "tobacco_unscreened_count": row["tobacco_unscreened_count"],
        "encounters_365d_total": row["encounters_365d_total"],
        "ed_visits_365d_total": row["ed_visits_365d_total"],
        "inpatient_admits_365d_total": row["inpatient_admits_365d_total"],
    }
