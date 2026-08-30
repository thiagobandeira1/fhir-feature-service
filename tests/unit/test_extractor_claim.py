"""Unit tests for the Claim diagnosis extractor."""

from datetime import date
from typing import Any

from fhir_features.canonical.models import ConditionRow
from fhir_features.fhir.extractors.claim import extract_claim_diagnoses

_PATIENT_URN = "urn:uuid:939eea26-a679-2564-5cf9-c0fd557beefc"
_COND1_URN = "urn:uuid:cond-0001"
_COND2_URN = "urn:uuid:cond-0002"
_UNEXTRACTED_URN = "urn:uuid:cond-not-extracted"
_REFMAP: dict[str, tuple[str, str]] = {
    _PATIENT_URN: ("Patient", "p1"),
    _COND1_URN: ("Condition", "c1"),
    _COND2_URN: ("Condition", "c2"),
    _UNEXTRACTED_URN: ("Condition", "c-ghost"),
}
_POINTER = "/entry/42/resource"


def _condition(condition_id: str, code: str) -> ConditionRow:
    return ConditionRow(
        condition_id=condition_id,
        patient_id="p1",
        code=code,
        code_system="SNOMED",
        code_display=f"Display for {code}",
        onset_date=date(2015, 6, 1),
        date_precision="day",
    )


_CONDITIONS = {
    "c1": _condition("c1", "44054006"),
    "c2": _condition("c2", "59621000"),
}


def _claim(**overrides: Any) -> dict[str, Any]:
    resource: dict[str, Any] = {
        "resourceType": "Claim",
        "id": "claim-1",
        "status": "active",
        "type": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/claim-type",
                    "code": "professional",
                }
            ]
        },
        "use": "claim",
        "patient": {"reference": _PATIENT_URN},
        "billablePeriod": {
            "start": "2019-03-14T11:38:04-04:00",
            "end": "2019-03-14T12:48:25-04:00",
        },
        "diagnosis": [
            {"sequence": 1, "diagnosisReference": {"reference": _COND1_URN}},
            {"sequence": 2, "diagnosisReference": {"reference": _COND2_URN}},
        ],
    }
    resource.update(overrides)
    return resource


class TestHappyPath:
    def test_two_diagnoses_resolve_in_sequence_order(self) -> None:
        rows, issues = extract_claim_diagnoses(_claim(), _REFMAP, _CONDITIONS, _POINTER)
        assert issues == []
        assert [r.diagnosis_sequence for r in rows] == [1, 2]
        first, second = rows
        assert first.claim_id == "claim-1"
        assert first.patient_id == "p1"
        assert first.claim_type == "professional"
        assert first.billable_period_start == date(2019, 3, 14)
        assert first.billable_period_end == date(2019, 3, 14)
        assert first.diagnosis_code == "44054006"
        assert first.diagnosis_code_system == "SNOMED"
        assert first.diagnosis_display == "Display for 44054006"
        assert first.resolved_condition_id == "c1"
        assert second.diagnosis_code == "59621000"
        assert second.resolved_condition_id == "c2"

    def test_evening_offset_keeps_local_billable_date(self) -> None:
        # 23:38 at -04:00 is already Mar 15 in UTC; the local date must stay Mar 14.
        resource = _claim(billablePeriod={"start": "2019-03-14T23:38:04-04:00"})
        rows, issues = extract_claim_diagnoses(resource, _REFMAP, _CONDITIONS, _POINTER)
        assert issues == []
        assert rows[0].billable_period_start == date(2019, 3, 14)
        assert rows[0].billable_period_end is None

    def test_absent_type_and_period_degrade_to_none(self) -> None:
        resource = _claim()
        del resource["type"]
        del resource["billablePeriod"]
        rows, issues = extract_claim_diagnoses(resource, _REFMAP, _CONDITIONS, _POINTER)
        assert issues == []
        assert rows[0].claim_type is None
        assert rows[0].billable_period_start is None
        assert rows[0].billable_period_end is None


class TestGates:
    def test_preauthorization_skipped_silently(self) -> None:
        resource = _claim(use="preauthorization")
        assert extract_claim_diagnoses(resource, _REFMAP, _CONDITIONS, _POINTER) == ([], [])

    def test_missing_use_skipped_silently(self) -> None:
        resource = _claim()
        del resource["use"]
        assert extract_claim_diagnoses(resource, _REFMAP, _CONDITIONS, _POINTER) == ([], [])

    def test_no_diagnosis_list_is_silent(self) -> None:
        # Synthea emits many pharmacy claims without diagnoses — no rows, no issues.
        resource = _claim(type={"coding": [{"code": "pharmacy"}]})
        del resource["diagnosis"]
        assert extract_claim_diagnoses(resource, _REFMAP, _CONDITIONS, _POINTER) == ([], [])

    def test_empty_diagnosis_list_is_silent(self) -> None:
        resource = _claim(diagnosis=[])
        assert extract_claim_diagnoses(resource, _REFMAP, _CONDITIONS, _POINTER) == ([], [])

    def test_codeable_concept_only_entry_skipped_silently(self) -> None:
        resource = _claim(
            diagnosis=[{"sequence": 1, "diagnosisCodeableConcept": {"coding": [{"code": "J20.9"}]}}]
        )
        assert extract_claim_diagnoses(resource, _REFMAP, _CONDITIONS, _POINTER) == ([], [])


class TestDrops:
    def test_missing_id_drops_with_issue(self) -> None:
        resource = _claim()
        del resource["id"]
        rows, issues = extract_claim_diagnoses(resource, _REFMAP, _CONDITIONS, _POINTER)
        assert rows == []
        assert [(i.code, i.json_pointer) for i in issues] == [
            ("claim_missing_id", f"{_POINTER}/id")
        ]

    def test_dangling_patient_reference(self) -> None:
        resource = _claim(patient={"reference": "urn:uuid:not-in-bundle"})
        rows, issues = extract_claim_diagnoses(resource, _REFMAP, _CONDITIONS, _POINTER)
        assert rows == []
        assert [(i.code, i.json_pointer) for i in issues] == [
            ("dangling_subject_reference", f"{_POINTER}/patient")
        ]

    def test_dangling_diagnosis_ref_skips_only_that_one(self) -> None:
        resource = _claim(
            diagnosis=[
                {"sequence": 1, "diagnosisReference": {"reference": _COND1_URN}},
                {"sequence": 2, "diagnosisReference": {"reference": "urn:uuid:nowhere"}},
            ]
        )
        rows, issues = extract_claim_diagnoses(resource, _REFMAP, _CONDITIONS, _POINTER)
        assert [r.resolved_condition_id for r in rows] == ["c1"]
        assert [(i.code, i.json_pointer) for i in issues] == [
            ("dangling_diagnosis_reference", f"{_POINTER}/diagnosis/1/diagnosisReference")
        ]

    def test_reference_to_condition_not_extracted_is_dangling(self) -> None:
        resource = _claim(
            diagnosis=[{"sequence": 1, "diagnosisReference": {"reference": _UNEXTRACTED_URN}}]
        )
        rows, issues = extract_claim_diagnoses(resource, _REFMAP, _CONDITIONS, _POINTER)
        assert rows == []
        assert issues[0].code == "dangling_diagnosis_reference"

    def test_missing_sequence_skips_entry_with_issue(self) -> None:
        resource = _claim(
            diagnosis=[
                {"diagnosisReference": {"reference": _COND1_URN}},
                {"sequence": 2, "diagnosisReference": {"reference": _COND2_URN}},
            ]
        )
        rows, issues = extract_claim_diagnoses(resource, _REFMAP, _CONDITIONS, _POINTER)
        assert [r.resolved_condition_id for r in rows] == ["c2"]
        assert [(i.code, i.json_pointer) for i in issues] == [
            ("diagnosis_missing_sequence", f"{_POINTER}/diagnosis/0/sequence")
        ]

    def test_garbage_billable_period_degrades_with_issue(self) -> None:
        resource = _claim(billablePeriod={"start": "not-a-date"})
        rows, issues = extract_claim_diagnoses(resource, _REFMAP, _CONDITIONS, _POINTER)
        assert len(rows) == 2
        assert rows[0].billable_period_start is None
        assert [(i.code, i.json_pointer) for i in issues] == [
            ("unparseable_billable_period", f"{_POINTER}/billablePeriod/start")
        ]
