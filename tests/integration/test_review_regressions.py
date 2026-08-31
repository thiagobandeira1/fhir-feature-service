"""Regression tests for defects found by the adversarial review.

Each test reproduces a confirmed finding's failure scenario and pins the fix.
"""

from datetime import date
from typing import Any

from fhir_features.adapters.synthea import record_set_from_bundle
from fhir_features.features.queries import compute_features
from fhir_features.store.db import Database
from fhir_features.store.loader import load_patient


def _bundle(*resources: dict[str, Any]) -> dict[str, Any]:
    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [{"fullUrl": f"urn:uuid:{r['id']}", "resource": r} for r in resources],
    }


def _patient(pid: str) -> dict[str, Any]:
    return {
        "resourceType": "Patient",
        "id": pid,
        "birthDate": "1950-01-01",
        "gender": "female",
    }


def _load(db: Database, payload: dict[str, Any]) -> None:
    load_patient(
        db,
        record_set_from_bundle(payload),
        bundle_hash=None,
        raw_payload=None,
        service_version="test",
    )


class TestInpatientDaysClamp:
    """Finding: LOS counted hospital days after as_of (future leakage)."""

    def test_mid_admission_as_of_counts_only_elapsed_days(self, db: Database) -> None:
        payload = _bundle(
            _patient("p1"),
            {
                "resourceType": "Encounter",
                "id": "e1",
                "status": "finished",
                "class": {"code": "IMP"},
                "subject": {"reference": "urn:uuid:p1"},
                "period": {
                    "start": "2023-06-01T08:00:00-05:00",
                    "end": "2023-07-01T10:00:00-05:00",
                },
            },
        )
        _load(db, payload)
        mid = compute_features(db, date(2023, 6, 15), patient_id="p1")[0]
        assert mid["inpatient_days_365d"] == 14  # elapsed days only, not the full 30
        after = compute_features(db, date(2023, 8, 1), patient_id="p1")[0]
        assert after["inpatient_days_365d"] == 30


class TestForeignSubjectDropped:
    """Finding: rows with a foreign Patient reference were stored under that patient."""

    def test_foreign_condition_dropped_with_warning(self, db: Database) -> None:
        payload = _bundle(
            _patient("p2"),
            {
                "resourceType": "Condition",
                "id": "c1",
                "subject": {"reference": "Patient/SOMEONE-ELSE"},
                "code": {"coding": [{"system": "http://snomed.info/sct", "code": "44054006"}]},
                "onsetDateTime": "2020-01-01T00:00:00Z",
            },
        )
        record_set = record_set_from_bundle(payload)
        assert record_set.conditions == []
        assert any(w.code == "foreign_subject_dropped" for w in record_set.warnings)
        _load(db, payload)  # must not raise on later re-ingest either
        _load(db, payload)


class TestDuplicateIds:
    """Finding: duplicate ids within one bundle crashed the whole ingest with a PK error."""

    def test_duplicate_component_codes_keep_first(self, db: Database) -> None:
        payload = _bundle(
            _patient("p3"),
            {
                "resourceType": "Observation",
                "id": "o1",
                "status": "final",
                "code": {"coding": [{"system": "http://loinc.org", "code": "85354-9"}]},
                "subject": {"reference": "urn:uuid:p3"},
                "effectiveDateTime": "2022-03-01T09:00:00Z",
                "component": [
                    {
                        "code": {"coding": [{"system": "http://loinc.org", "code": "8480-6"}]},
                        "valueQuantity": {"value": 120, "unit": "mm[Hg]"},
                    },
                    {
                        "code": {"coding": [{"system": "http://loinc.org", "code": "8480-6"}]},
                        "valueQuantity": {"value": 999, "unit": "mm[Hg]"},
                    },
                ],
            },
        )
        record_set = record_set_from_bundle(payload)
        child_values = [
            o.value_num for o in record_set.observations if o.parent_observation_id == "o1"
        ]
        assert child_values == [120]  # first kept, duplicate dropped
        assert any(w.code == "duplicate_component_code" for w in record_set.warnings)
        _load(db, payload)  # and the load survives

    def test_duplicate_resource_ids_keep_first(self, db: Database) -> None:
        cond = {
            "resourceType": "Condition",
            "id": "dup",
            "subject": {"reference": "urn:uuid:p4"},
            "code": {"coding": [{"system": "http://snomed.info/sct", "code": "38341003"}]},
            "onsetDateTime": "2019-05-01T00:00:00Z",
        }
        payload = _bundle(_patient("p4"), cond, dict(cond))
        record_set = record_set_from_bundle(payload)
        assert len(record_set.conditions) == 1
        assert any(w.code == "duplicate_resource_id" for w in record_set.warnings)
        _load(db, payload)


class TestUnbornPatientsExcluded:
    """Finding: patients not yet born at as_of got rows with negative ages."""

    def test_no_feature_row_before_birth(self, db: Database) -> None:
        _load(db, _bundle(_patient("p5")))
        assert compute_features(db, date(1940, 1, 1), patient_id="p5") == []
        rows = compute_features(db, date(1950, 1, 1), patient_id="p5")
        assert len(rows) == 1
        assert rows[0]["age_years"] == 0


class TestDeceasedBooleanVisibility:
    """Finding: deceasedBoolean was silently ignored."""

    def test_deceased_boolean_without_date_warns(self) -> None:
        patient = _patient("p6") | {"deceasedBoolean": True}
        record_set = record_set_from_bundle(_bundle(patient))
        assert any(w.code == "deceased_boolean_without_date" for w in record_set.warnings)
