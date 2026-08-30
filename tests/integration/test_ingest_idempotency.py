"""Idempotent ingestion via the loader: sha256 no-op detection, replace-by-patient, no orphans.

Exercises ``store.loader`` + ``adapters.synthea`` directly against the migrated ``db`` fixture
(no HTTP): same-content reloads are detectable and stable, and a mutated bundle atomically
replaces the previous rows without leaving orphans in child tables.
"""

import copy
import json
from typing import Any

from fhir_features.adapters.synthea import record_set_from_bundle
from fhir_features.canonical.models import PatientRecordSet
from fhir_features.fhir.bundle import canonical_bundle_hash
from fhir_features.store.db import Database
from fhir_features.store.loader import LoadResult, bundle_already_loaded, load_patient

SERVICE_VERSION = "test"

_PER_PATIENT_TABLES = (
    "patients",
    "encounters",
    "conditions",
    "observations",
    "procedures",
    "medication_requests",
    "immunizations",
    "claim_diagnoses",
)

_CHANGED_VALUE = 999.25  # exactly representable in binary and in DECIMAL(18, 6)


def _load(db: Database, payload: dict[str, Any]) -> tuple[LoadResult, PatientRecordSet, str]:
    """Run the CLI/API caller path: parse, hash, load; return everything a test needs."""
    record_set = record_set_from_bundle(payload)
    bundle_hash = canonical_bundle_hash(payload)
    result = load_patient(
        db,
        record_set,
        bundle_hash=bundle_hash,
        raw_payload=json.dumps(payload, separators=(",", ":")),
        service_version=SERVICE_VERSION,
    )
    return result, record_set, bundle_hash


def _expected_counts(record_set: PatientRecordSet) -> dict[str, int]:
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


def _one(db: Database, sql: str, params: list[Any] | None = None) -> tuple[Any, ...]:
    row = db.conn.execute(sql, params).fetchone()
    assert row is not None
    return tuple(row)


def _db_counts(db: Database, patient_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in _PER_PATIENT_TABLES:
        row = _one(
            db,
            f"SELECT count(*) FROM {table} WHERE source = 'synthea' AND patient_id = ?",
            [patient_id],
        )
        counts[table] = int(row[0])
    # resource_codings has no patient_id column; these tests load exactly one patient.
    row = _one(db, "SELECT count(*) FROM resource_codings WHERE source = 'synthea'")
    counts["resource_codings"] = int(row[0])
    return counts


def _ingest_log_actions(db: Database, patient_id: str) -> list[tuple[str, str | None]]:
    rows = db.conn.execute(
        "SELECT action, bundle_hash FROM ingest_log"
        " WHERE source = 'synthea' AND patient_id = ? ORDER BY started_at",
        [patient_id],
    ).fetchall()
    return [(row[0], row[1]) for row in rows]


def test_reingest_same_content_is_detected_and_leaves_counts_stable(
    db: Database, diabetic_bundle: dict[str, Any]
) -> None:
    first, record_set, bundle_hash = _load(db, diabetic_bundle)
    patient_id = record_set.patient.patient_id
    assert first.action == "created"

    # The caller path: same content is recognized as already the stored state.
    assert bundle_already_loaded(db, bundle_hash) is True

    # Load again anyway (a caller that skipped the no-op check): replace, not duplicate.
    second, _, second_hash = _load(db, diabetic_bundle)
    assert second_hash == bundle_hash
    assert second.action == "replaced"
    assert second.row_counts == first.row_counts

    expected = _expected_counts(record_set)
    assert second.row_counts == expected
    assert _db_counts(db, patient_id) == expected  # equal counts == no duplicate rows

    # raw_bundles keeps exactly one (latest) row per patient across both loads.
    raw = db.conn.execute(
        "SELECT bundle_hash FROM raw_bundles WHERE source = 'synthea' AND patient_id = ?",
        [patient_id],
    ).fetchall()
    assert [row[0] for row in raw] == [bundle_hash]

    assert _ingest_log_actions(db, patient_id) == [
        ("created", bundle_hash),
        ("replaced", bundle_hash),
    ]


def _mutate_bundle(payload: dict[str, Any]) -> tuple[dict[str, Any], str, str, float]:
    """Deepcopy the payload, drop one Condition entry, change one Observation valueQuantity.

    Returns (mutated_payload, removed_condition_resource_id, changed_observation_id, old_value).
    """
    mutated = copy.deepcopy(payload)
    entries: list[dict[str, Any]] = mutated["entry"]

    cond_index = next(
        i for i, e in enumerate(entries) if e["resource"]["resourceType"] == "Condition"
    )
    removed_condition_id: str = entries[cond_index]["resource"]["id"]
    del entries[cond_index]

    obs_resource = next(
        e["resource"]
        for e in entries
        if e["resource"]["resourceType"] == "Observation"
        and e["resource"].get("status") == "final"
        and isinstance(e["resource"].get("valueQuantity"), dict)
        and "component" not in e["resource"]
    )
    old_value = float(obs_resource["valueQuantity"]["value"])
    assert old_value != _CHANGED_VALUE
    obs_resource["valueQuantity"]["value"] = _CHANGED_VALUE
    return mutated, removed_condition_id, obs_resource["id"], old_value


def test_mutated_bundle_replaces_patient_without_orphans(
    db: Database, diabetic_bundle: dict[str, Any]
) -> None:
    first, original_rs, original_hash = _load(db, diabetic_bundle)
    patient_id = original_rs.patient.patient_id
    assert first.action == "created"

    mutated, removed_condition_id, changed_obs_id, old_value = _mutate_bundle(diabetic_bundle)

    # Sanity: the row we will assert gone is actually part of the original stored state.
    assert removed_condition_id in {c.condition_id for c in original_rs.conditions}
    cond_row = _one(
        db,
        "SELECT count(*) FROM conditions WHERE source = 'synthea' AND condition_id = ?",
        [removed_condition_id],
    )
    assert cond_row[0] == 1
    coding_count_before = _one(
        db,
        "SELECT count(*) FROM resource_codings WHERE source = 'synthea' AND resource_id = ?",
        [removed_condition_id],
    )[0]
    assert coding_count_before >= 1
    stored_old = _one(
        db,
        "SELECT value_num FROM observations WHERE source = 'synthea' AND observation_id = ?",
        [changed_obs_id],
    )
    assert float(stored_old[0]) == old_value

    mutated_hash = canonical_bundle_hash(mutated)
    assert mutated_hash != original_hash
    assert bundle_already_loaded(db, mutated_hash) is False

    result, mutated_rs, loaded_hash = _load(db, mutated)
    assert loaded_hash == mutated_hash
    assert result.action == "replaced"
    assert len(mutated_rs.conditions) == len(original_rs.conditions) - 1

    # The removed condition's row is gone, and its codings left no orphans behind.
    assert (
        _one(
            db,
            "SELECT count(*) FROM conditions WHERE source = 'synthea' AND condition_id = ?",
            [removed_condition_id],
        )[0]
        == 0
    )
    assert (
        _one(
            db,
            "SELECT count(*) FROM resource_codings WHERE source = 'synthea' AND resource_id = ?",
            [removed_condition_id],
        )[0]
        == 0
    )

    # The changed observation's value was updated in place (same id, new value).
    row = _one(
        db,
        "SELECT value_num FROM observations WHERE source = 'synthea' AND observation_id = ?",
        [changed_obs_id],
    )
    assert float(row[0]) == _CHANGED_VALUE

    # Whole-table counts equal the mutated record set: replace-by-patient left nothing extra.
    assert _db_counts(db, patient_id) == _expected_counts(mutated_rs)

    # raw_bundles holds exactly one row for the patient — the latest content.
    raw = db.conn.execute(
        "SELECT bundle_hash FROM raw_bundles WHERE source = 'synthea' AND patient_id = ?",
        [patient_id],
    ).fetchall()
    assert [r[0] for r in raw] == [mutated_hash]

    # One audit row per load, each with the hash it loaded.
    assert _ingest_log_actions(db, patient_id) == [
        ("created", original_hash),
        ("replaced", mutated_hash),
    ]

    # The audit row's resource_counts mirror what was actually loaded.
    logged = _one(
        db,
        "SELECT resource_counts FROM ingest_log"
        " WHERE source = 'synthea' AND patient_id = ? AND action = 'replaced'",
        [patient_id],
    )
    assert json.loads(logged[0])["rows"] == _expected_counts(mutated_rs)
