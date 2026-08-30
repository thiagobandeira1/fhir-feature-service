"""Reparse end-to-end: rebuild canonical tables from retained raw bundles.

Simulates the real operational sequence: a bundle is ingested via the CLI code path
(``record_set_from_bundle`` + ``load_patient`` with the raw payload retained), canonical rows
are then damaged (as a stand-in for "an old extractor bug parsed them wrong"), and
``fhir_features.cli.cmd_reparse`` — pointed at the same DuckDB file via ``FF_DB_PATH`` —
restores them from ``raw_bundles`` and audits the pass as ``reparsed``.
"""

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

from fhir_features.adapters.synthea import load_bundle_file, record_set_from_bundle
from fhir_features.cli import cmd_reparse
from fhir_features.fhir.bundle import canonical_bundle_hash
from fhir_features.store.db import Database
from fhir_features.store.loader import load_patient

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "synthetic" / "samples"
SERVICE_VERSION = "test"


@pytest.fixture(scope="module")
def smallest_bundle() -> dict[str, Any]:
    (path,) = sorted(SAMPLES_DIR.glob("Chet188*.json.gz"))
    payload: dict[str, Any] = load_bundle_file(path)
    return payload


def _observation_rows(db: Database, patient_id: str) -> list[tuple[Any, ...]]:
    return db.conn.execute(
        "SELECT observation_id, parent_observation_id, code, value_num, value_text,"
        " effective_date, status"
        " FROM observations WHERE source = 'synthea' AND patient_id = ?"
        " ORDER BY observation_id",
        [patient_id],
    ).fetchall()


def test_cmd_reparse_restores_deleted_canonical_rows(
    db: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    smallest_bundle: dict[str, Any],
) -> None:
    # Ingest via the CLI code path, retaining the raw payload for later reparse.
    record_set = record_set_from_bundle(smallest_bundle)
    bundle_hash = canonical_bundle_hash(smallest_bundle)
    result = load_patient(
        db,
        record_set,
        bundle_hash=bundle_hash,
        raw_payload=json.dumps(smallest_bundle, separators=(",", ":")),
        service_version=SERVICE_VERSION,
    )
    assert result.action == "created"
    patient_id = record_set.patient.patient_id

    baseline = _observation_rows(db, patient_id)
    assert len(baseline) == len(record_set.observations)
    assert baseline, "persona must have observations for the test to mean anything"

    # Simulate a bad old parse: canonical rows are missing, but the raw bundle is retained.
    db.conn.execute(
        "DELETE FROM observations WHERE source = 'synthea' AND patient_id = ?", [patient_id]
    )
    assert _observation_rows(db, patient_id) == []

    # Run the real CLI command against the same database file.
    monkeypatch.setenv("FF_DB_PATH", str(tmp_path / "test.duckdb"))
    assert cmd_reparse(argparse.Namespace()) == 0

    # Every deleted row is back, value-identical to the original parse.
    assert _observation_rows(db, patient_id) == baseline

    # The audit log records one row per pass with the right actions and the same hash.
    log_rows = db.conn.execute(
        "SELECT action, bundle_hash FROM ingest_log"
        " WHERE source = 'synthea' AND patient_id = ? ORDER BY started_at",
        [patient_id],
    ).fetchall()
    assert [(row[0], row[1]) for row in log_rows] == [
        ("created", bundle_hash),
        ("reparsed", bundle_hash),
    ]

    # Reparse rebuilds from the retained payload without duplicating or replacing it.
    raw = db.conn.execute(
        "SELECT bundle_hash FROM raw_bundles WHERE source = 'synthea' AND patient_id = ?",
        [patient_id],
    ).fetchall()
    assert [row[0] for row in raw] == [bundle_hash]
