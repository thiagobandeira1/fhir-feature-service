"""Golden feature tests at two pinned ``as_of`` dates — the trust core (SPEC section 9.4).

The committed goldens under ``tests/golden/`` are the behavioural contract of
``patient_features_v1.sql``. They regenerate ONLY via ``scripts/regen_goldens.py`` so every
change to feature semantics lands as a reviewable diff. Alongside exact-match tests, this
module proves the anti-leakage guarantee directly: an event after ``as_of`` can never
influence a feature at ``as_of``.
"""

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

import fhir_features
from conftest import load_sample_bundle
from fhir_features.adapters.synthea import record_set_from_bundle
from fhir_features.canonical.models import PatientRecordSet
from fhir_features.features.queries import compute_features
from fhir_features.features.value_sets import load_value_sets
from fhir_features.store.db import Database
from fhir_features.store.loader import load_patient
from fhir_features.store.reference import sync_value_sets
from golden_util import serialize_feature_rows

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "golden"
PERSONA_PREFIXES = ("Chet188", "Kayce253", "Meredith572", "Sheryl275", "Tony646")

AS_OF_EARLY = date(2023, 6, 30)
AS_OF_LATE = date(2025, 12, 31)
PINNED_AS_OF_DATES = (AS_OF_EARLY, AS_OF_LATE)

# Concrete persona anchors (guard queries below re-verify them against the loaded rows,
# so a silently swapped sample fails loudly instead of hollowing the test out).
TONY_PATIENT_ID = "939eea26-a679-2564-5cf9-c0fd557beefc"  # diabetic persona
KAYCE_PATIENT_ID = "009969ab-f1b8-a2c0-9fb7-f0621d7beea8"  # deceased persona


@pytest.fixture(scope="session")
def persona_record_sets() -> tuple[PatientRecordSet, ...]:
    """Parse all five committed persona bundles once per session (parsing dominates runtime)."""
    return tuple(record_set_from_bundle(load_sample_bundle(p)) for p in PERSONA_PREFIXES)


@pytest.fixture()
def loaded_db(db: Database, persona_record_sets: tuple[PatientRecordSet, ...]) -> Database:
    """The migrated tmp DB with value sets synced and all five personas ingested."""
    sync_value_sets(db, load_value_sets())
    for record_set in persona_record_sets:
        load_patient(
            db,
            record_set,
            bundle_hash=None,
            raw_payload=None,
            service_version=fhir_features.__version__,
        )
    return db


@pytest.mark.parametrize("as_of", PINNED_AS_OF_DATES, ids=str)
def test_matches_golden(loaded_db: Database, as_of: date) -> None:
    rows = compute_features(loaded_db, as_of)
    assert len(rows) == len(PERSONA_PREFIXES)
    serialized = serialize_feature_rows(rows)
    golden_path = GOLDEN_DIR / f"features_{as_of.isoformat()}.json"
    golden_text = golden_path.read_text(encoding="utf-8")
    message = (
        f"feature output diverged from {golden_path.name}. If the change is intentional, "
        "run `uv run python scripts/regen_goldens.py` and review the resulting diff before "
        "committing; if not, you introduced a feature regression."
    )
    # Structural comparison first (readable pytest diff), then exact text (formatting drift).
    assert json.loads(serialized) == json.loads(golden_text), message
    assert serialized == golden_text, message


def test_no_feature_date_exceeds_as_of(loaded_db: Database) -> None:
    """Every last_*/latest_*/status date in an early-as_of row must be <= that as_of."""
    rows = compute_features(loaded_db, AS_OF_EARLY)
    date_keys = {key for row in rows for key in row if key.endswith("_date")}
    # The registry defines 10 event-date features; the suffix scan must find all of them.
    assert date_keys == {
        "latest_bp_date",
        "latest_hba1c_date",
        "latest_bmi_date",
        "tobacco_status_date",
        "last_statin_authored_date",
        "last_mammogram_date",
        "last_colonoscopy_date",
        "last_fobt_fit_date",
        "last_retinal_exam_date",
        "last_flu_immunization_date",
    }
    non_null_seen = 0
    for row in rows:
        for key in date_keys:
            value = row[key]
            if value is None:
                continue
            non_null_seen += 1
            assert isinstance(value, date)
            assert value <= AS_OF_EARLY, (
                f"{key}={value} for patient {row['patient_id']} leaks past as_of {AS_OF_EARLY}"
            )
    assert non_null_seen > 0, "no non-null event dates at all — the assertion never bit"


def test_encounters_365d_counts_only_the_trailing_window(loaded_db: Database) -> None:
    """encounters_365d at 2023-06-30 counts starts in (2022-06-30, 2023-06-30] only."""
    window_start = AS_OF_EARLY - timedelta(days=365)
    assert window_start == date(2022, 6, 30)
    rows = compute_features(loaded_db, AS_OF_EARLY)
    a_patient_had_older_encounters = False
    for row in rows:
        counts = loaded_db.conn.execute(
            """
            SELECT
                count(*) FILTER (WHERE start_date > ? AND start_date <= ?) AS in_window,
                count(*) FILTER (WHERE start_date <= ?) AS on_or_before_as_of
            FROM encounters
            WHERE source = ? AND patient_id = ?
            """,
            [window_start, AS_OF_EARLY, AS_OF_EARLY, row["source"], row["patient_id"]],
        ).fetchone()
        assert counts is not None
        in_window, on_or_before_as_of = counts
        assert row["encounters_365d"] == in_window, (
            f"patient {row['patient_id']}: encounters_365d={row['encounters_365d']} "
            f"but (2022-06-30, 2023-06-30] holds {in_window} encounter starts"
        )
        if on_or_before_as_of > in_window:
            a_patient_had_older_encounters = True
    assert a_patient_had_older_encounters, (
        "every historical encounter fell inside the window — the test never exercised exclusion"
    )


def test_late_onset_condition_does_not_set_chronic_flag_early(loaded_db: Database) -> None:
    """Tony646's diabetes onsets 2025-12-25: invisible at 2023-06-30, active at 2025-12-31."""
    # Guard: the concrete example must still exist in the committed sample.
    conditions = loaded_db.conn.execute(
        """
        SELECT c.onset_date, c.abatement_date
        FROM conditions c
        JOIN value_set_members v ON v.code_system = c.code_system AND v.code = c.code
        WHERE v.value_set_id = 'diabetes_snomed' AND c.source = 'synthea' AND c.patient_id = ?
        ORDER BY c.onset_date
        """,
        [TONY_PATIENT_ID],
    ).fetchall()
    assert conditions == [(date(2025, 12, 25), None)], (
        "the Tony646 sample no longer carries exactly one diabetes condition with onset "
        "2025-12-25 — re-pick the anti-leakage example (see scripts/regen_goldens.py probe)"
    )

    (early_row,) = compute_features(loaded_db, AS_OF_EARLY, patient_id=TONY_PATIENT_ID)
    (late_row,) = compute_features(loaded_db, AS_OF_LATE, patient_id=TONY_PATIENT_ID)
    assert early_row["has_diabetes"] is False, "future-onset diabetes leaked into 2023-06-30"
    assert late_row["has_diabetes"] is True
    # Same patient, long-standing hypertension (onset 2000-08-03): TRUE at both dates —
    # the flip above is driven by the onset date, not by the patient or the value set join.
    assert early_row["has_hypertension"] is True
    assert late_row["has_hypertension"] is True


def test_is_deceased_flips_exactly_at_death_date(loaded_db: Database) -> None:
    deaths = loaded_db.conn.execute(
        "SELECT patient_id, death_date FROM patients WHERE death_date IS NOT NULL"
    ).fetchall()
    assert len(deaths) == 1, "expected exactly one deceased persona (Kayce253)"
    patient_id, death_date = deaths[0]
    assert patient_id == KAYCE_PATIENT_ID
    assert isinstance(death_date, date)

    (before_row,) = compute_features(
        loaded_db, death_date - timedelta(days=1), patient_id=patient_id
    )
    (on_row,) = compute_features(loaded_db, death_date, patient_id=patient_id)
    (early_row,) = compute_features(loaded_db, AS_OF_EARLY, patient_id=patient_id)
    assert before_row["is_deceased"] is False, "death leaked into an as_of before death_date"
    assert on_row["is_deceased"] is True
    assert early_row["is_deceased"] is True


@pytest.mark.parametrize("as_of", PINNED_AS_OF_DATES, ids=str)
def test_feature_computation_is_deterministic(loaded_db: Database, as_of: date) -> None:
    first: list[dict[str, Any]] = compute_features(loaded_db, as_of)
    second: list[dict[str, Any]] = compute_features(loaded_db, as_of)
    assert serialize_feature_rows(first) == serialize_feature_rows(second)
