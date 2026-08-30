"""Unit tests for the Observation extractor — code-keyed component flattening above all."""

from datetime import UTC, date, datetime
from typing import Any

import pytest

from fhir_features.fhir.extractors.observation import extract_observation

POINTER = "/entry/7/resource"
PATIENT_URN = "urn:uuid:pat-1"
ENCOUNTER_URN = "urn:uuid:enc-1"
REFMAP: dict[str, tuple[str, str]] = {
    PATIENT_URN: ("Patient", "pat-1"),
    ENCOUNTER_URN: ("Encounter", "enc-1"),
}
LOINC = "http://loinc.org"
SNOMED = "http://snomed.info/sct"
UCUM = "http://unitsofmeasure.org"
CATEGORY_SYSTEM = "http://terminology.hl7.org/CodeSystem/observation-category"


def _hba1c() -> dict[str, Any]:
    """A Synthea-shaped laboratory Observation carrying a valueQuantity."""
    return {
        "resourceType": "Observation",
        "id": "obs-a1c",
        "status": "final",
        "category": [{"coding": [{"system": CATEGORY_SYSTEM, "code": "laboratory"}]}],
        "code": {"coding": [{"system": LOINC, "code": "4548-4", "display": "Hemoglobin A1c"}]},
        "subject": {"reference": PATIENT_URN},
        "encounter": {"reference": ENCOUNTER_URN},
        "effectiveDateTime": "2016-11-03T11:38:04-04:00",
        "issued": "2016-11-03T11:38:04.681-04:00",
        "valueQuantity": {"value": 5.81, "unit": "percent", "system": UCUM, "code": "%"},
    }


def _tobacco() -> dict[str, Any]:
    """A Synthea-shaped smoking-status Observation carrying a valueCodeableConcept."""
    resource = _hba1c()
    resource["id"] = "obs-tobacco"
    resource["code"] = {
        "coding": [{"system": LOINC, "code": "72166-2", "display": "Tobacco smoking status"}]
    }
    del resource["valueQuantity"]
    resource["valueCodeableConcept"] = {
        "coding": [
            {"system": SNOMED, "code": "266919005", "display": "Never smoked tobacco (finding)"}
        ]
    }
    return resource


def _bp_panel() -> dict[str, Any]:
    """A Synthea-shaped blood-pressure panel with diastolic + systolic components."""
    return {
        "resourceType": "Observation",
        "id": "obs-bp",
        "status": "final",
        "category": [{"coding": [{"system": CATEGORY_SYSTEM, "code": "vital-signs"}]}],
        "code": {
            "coding": [{"system": LOINC, "code": "85354-9", "display": "Blood pressure panel"}]
        },
        "subject": {"reference": PATIENT_URN},
        "encounter": {"reference": ENCOUNTER_URN},
        "effectiveDateTime": "2016-11-03T11:38:04-04:00",
        "component": [
            {
                "code": {
                    "coding": [
                        {"system": LOINC, "code": "8462-4", "display": "Diastolic Blood Pressure"}
                    ]
                },
                "valueQuantity": {"value": 89, "unit": "mm[Hg]", "system": UCUM, "code": "mm[Hg]"},
            },
            {
                "code": {
                    "coding": [
                        {"system": LOINC, "code": "8480-6", "display": "Systolic Blood Pressure"}
                    ]
                },
                "valueQuantity": {"value": 129, "unit": "mm[Hg]", "system": UCUM, "code": "mm[Hg]"},
            },
        ],
    }


class TestHappyPath:
    def test_value_quantity_row(self) -> None:
        rows, issues = extract_observation(_hba1c(), REFMAP, POINTER)
        assert issues == []
        assert len(rows) == 1
        row = rows[0]
        assert row.observation_id == "obs-a1c"
        assert row.parent_observation_id is None
        assert row.patient_id == "pat-1"
        assert row.encounter_id == "enc-1"
        assert row.code == "4548-4"
        assert row.code_system == "LOINC"
        assert row.code_display == "Hemoglobin A1c"
        assert row.category == "laboratory"
        assert row.effective_ts == datetime(2016, 11, 3, 15, 38, 4, tzinfo=UTC)
        assert row.effective_date == date(2016, 11, 3)
        assert row.date_precision == "second"
        assert row.value_num == 5.81
        assert row.value_unit == "%"  # the UCUM code wins over the free-text unit
        assert row.value_code is None
        assert row.value_text is None
        assert row.status == "final"

    def test_value_codeable_concept_tobacco_answer(self) -> None:
        rows, issues = extract_observation(_tobacco(), REFMAP, POINTER)
        assert issues == []
        assert len(rows) == 1
        row = rows[0]
        assert row.code == "72166-2"
        assert row.value_code == "266919005"
        assert row.value_code_system == "SNOMED"
        assert row.value_num is None
        assert row.value_unit is None

    def test_value_string(self) -> None:
        resource = _hba1c()
        del resource["valueQuantity"]
        resource["valueString"] = "trace"
        rows, issues = extract_observation(resource, REFMAP, POINTER)
        assert issues == []
        assert rows[0].value_text == "trace"
        assert rows[0].value_num is None

    def test_relative_literal_subject_reference(self) -> None:
        resource = _hba1c()
        resource["subject"] = {"reference": "Patient/pat-9"}
        rows, issues = extract_observation(resource, REFMAP, POINTER)
        assert issues == []
        assert rows[0].patient_id == "pat-9"


class TestStatusFilter:
    @pytest.mark.parametrize("status", ["final", "amended", "corrected"])
    def test_stored_statuses_kept(self, status: str) -> None:
        resource = _hba1c()
        resource["status"] = status
        rows, issues = extract_observation(resource, REFMAP, POINTER)
        assert len(rows) == 1
        assert rows[0].status == status
        assert issues == []

    @pytest.mark.parametrize(
        "status", ["preliminary", "registered", "cancelled", "entered-in-error", "unknown", 7]
    )
    def test_other_statuses_filtered_silently(self, status: Any) -> None:
        resource = _hba1c()
        resource["status"] = status
        assert extract_observation(resource, REFMAP, POINTER) == ([], [])

    def test_missing_status_filtered_silently(self) -> None:
        resource = _hba1c()
        del resource["status"]
        assert extract_observation(resource, REFMAP, POINTER) == ([], [])


class TestDroppedRows:
    def test_missing_id(self) -> None:
        resource = _hba1c()
        del resource["id"]
        rows, issues = extract_observation(resource, REFMAP, POINTER)
        assert rows == []
        assert [(i.code, i.json_pointer) for i in issues] == [
            ("observation_missing_id", f"{POINTER}/id")
        ]

    def test_missing_code(self) -> None:
        resource = _hba1c()
        del resource["code"]
        rows, issues = extract_observation(resource, REFMAP, POINTER)
        assert rows == []
        assert [(i.code, i.json_pointer) for i in issues] == [
            ("observation_missing_code", f"{POINTER}/code")
        ]

    def test_codings_without_codes_drop_row(self) -> None:
        resource = _hba1c()
        resource["code"] = {"coding": [{"system": LOINC, "display": "no code here"}]}
        rows, issues = extract_observation(resource, REFMAP, POINTER)
        assert rows == []
        assert issues[0].code == "observation_missing_code"

    def test_dangling_subject_reference(self) -> None:
        resource = _hba1c()
        resource["subject"] = {"reference": "urn:uuid:nowhere"}
        rows, issues = extract_observation(resource, REFMAP, POINTER)
        assert rows == []
        assert [(i.code, i.json_pointer) for i in issues] == [
            ("dangling_subject_reference", f"{POINTER}/subject/reference")
        ]

    def test_subject_resolving_to_non_patient_drops(self) -> None:
        resource = _hba1c()
        resource["subject"] = {"reference": ENCOUNTER_URN}
        rows, issues = extract_observation(resource, REFMAP, POINTER)
        assert rows == []
        assert issues[0].code == "dangling_subject_reference"

    def test_missing_subject_drops(self) -> None:
        resource = _hba1c()
        del resource["subject"]
        rows, issues = extract_observation(resource, REFMAP, POINTER)
        assert rows == []
        assert issues[0].code == "dangling_subject_reference"

    def test_garbage_effective_and_issued_drops(self) -> None:
        resource = _hba1c()
        resource["effectiveDateTime"] = "not-a-date"
        resource["issued"] = "also-garbage"
        rows, issues = extract_observation(resource, REFMAP, POINTER)
        assert rows == []
        assert [(i.code, i.json_pointer) for i in issues] == [
            ("observation_missing_effective", f"{POINTER}/effectiveDateTime")
        ]

    def test_missing_effective_and_issued_drops(self) -> None:
        resource = _hba1c()
        del resource["effectiveDateTime"]
        del resource["issued"]
        rows, issues = extract_observation(resource, REFMAP, POINTER)
        assert rows == []
        assert issues[0].code == "observation_missing_effective"


class TestEffectiveImputation:
    def test_missing_effective_falls_back_to_issued_with_issue(self) -> None:
        resource = _hba1c()
        del resource["effectiveDateTime"]
        resource["issued"] = "2020-01-15T09:00:00Z"
        rows, issues = extract_observation(resource, REFMAP, POINTER)
        assert len(rows) == 1
        assert rows[0].effective_date == date(2020, 1, 15)
        assert rows[0].effective_ts == datetime(2020, 1, 15, 9, 0, tzinfo=UTC)
        assert [(i.code, i.json_pointer) for i in issues] == [
            ("effective_imputed_from_issued", f"{POINTER}/effectiveDateTime")
        ]

    def test_garbage_effective_falls_back_to_issued_with_issue(self) -> None:
        resource = _hba1c()
        resource["effectiveDateTime"] = "garbage"
        rows, issues = extract_observation(resource, REFMAP, POINTER)
        assert len(rows) == 1
        assert rows[0].effective_date == date(2016, 11, 3)
        assert issues[0].code == "effective_imputed_from_issued"


class TestDegradation:
    def test_dangling_encounter_reference_nulls_fk_and_warns(self) -> None:
        resource = _hba1c()
        resource["encounter"] = {"reference": "urn:uuid:nowhere"}
        rows, issues = extract_observation(resource, REFMAP, POINTER)
        assert len(rows) == 1
        assert rows[0].encounter_id is None
        assert [(i.code, i.json_pointer) for i in issues] == [
            ("dangling_encounter_reference", f"{POINTER}/encounter/reference")
        ]

    def test_missing_encounter_and_category_degrade_silently(self) -> None:
        resource = _hba1c()
        del resource["encounter"]
        del resource["category"]
        rows, issues = extract_observation(resource, REFMAP, POINTER)
        assert issues == []
        assert rows[0].encounter_id is None
        assert rows[0].category is None

    def test_non_numeric_quantity_value_degrades_to_none(self) -> None:
        resource = _hba1c()
        resource["valueQuantity"] = {"value": "high", "unit": "%"}
        rows, issues = extract_observation(resource, REFMAP, POINTER)
        assert issues == []
        assert rows[0].value_num is None
        assert rows[0].value_unit == "%"


class TestComponentFlattening:
    def test_bp_panel_yields_parent_plus_two_children(self) -> None:
        rows, issues = extract_observation(_bp_panel(), REFMAP, POINTER)
        assert issues == []
        assert len(rows) == 3

        parent = rows[0]
        assert parent.observation_id == "obs-bp"
        assert parent.parent_observation_id is None
        assert parent.code == "85354-9"
        assert parent.value_num is None

        by_id = {row.observation_id: row for row in rows[1:]}
        assert set(by_id) == {"obs-bp#8462-4", "obs-bp#8480-6"}
        assert by_id["obs-bp#8462-4"].value_num == 89.0
        assert by_id["obs-bp#8480-6"].value_num == 129.0
        for child in by_id.values():
            assert child.parent_observation_id == "obs-bp"
            assert child.code_system == "LOINC"
            assert child.value_unit == "mm[Hg]"
            assert child.patient_id == parent.patient_id
            assert child.encounter_id == parent.encounter_id
            assert child.effective_ts == parent.effective_ts
            assert child.effective_date == parent.effective_date
            assert child.date_precision == parent.date_precision
            assert child.category == "vital-signs"
            assert child.status == "final"

    def test_child_ids_stable_when_component_order_reversed(self) -> None:
        reordered = _bp_panel()
        reordered["component"] = list(reversed(reordered["component"]))
        rows_fwd, _ = extract_observation(_bp_panel(), REFMAP, POINTER)
        rows_rev, _ = extract_observation(reordered, REFMAP, POINTER)
        fwd = {row.observation_id: row.value_num for row in rows_fwd}
        rev = {row.observation_id: row.value_num for row in rows_rev}
        assert fwd == rev  # ids are keyed by CODE, so reordering must not change them
        assert set(fwd) == {"obs-bp", "obs-bp#8462-4", "obs-bp#8480-6"}

    def test_component_without_value_quantity_skipped_without_issue(self) -> None:
        resource = _bp_panel()
        resource["component"].append(
            {
                "code": {"coding": [{"system": LOINC, "code": "8478-0", "display": "MAP"}]},
                "valueCodeableConcept": {"coding": [{"system": SNOMED, "code": "371911009"}]},
            }
        )
        rows, issues = extract_observation(resource, REFMAP, POINTER)
        assert issues == []
        assert len(rows) == 3  # the quantity-less component emits no child row

    def test_component_without_code_skipped_without_issue(self) -> None:
        resource = _bp_panel()
        resource["component"].append(
            {"valueQuantity": {"value": 70, "unit": "mm[Hg]", "system": UCUM, "code": "mm[Hg]"}}
        )
        rows, issues = extract_observation(resource, REFMAP, POINTER)
        assert issues == []
        assert len(rows) == 3

    def test_malformed_component_entries_never_raise(self) -> None:
        resource = _bp_panel()
        resource["component"].extend(["junk", 42, {"code": "not-a-concept"}])
        rows, issues = extract_observation(resource, REFMAP, POINTER)
        assert issues == []
        assert len(rows) == 3
