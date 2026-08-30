"""Unit tests for the Immunization extractor."""

from datetime import date
from typing import Any

from fhir_features.fhir.extractors.immunization import extract_immunization

_PATIENT_URN = "urn:uuid:939eea26-a679-2564-5cf9-c0fd557beefc"
_REFMAP: dict[str, tuple[str, str]] = {_PATIENT_URN: ("Patient", "p1")}
_POINTER = "/entry/7/resource"


def _immunization(**overrides: Any) -> dict[str, Any]:
    resource: dict[str, Any] = {
        "resourceType": "Immunization",
        "id": "imm-1",
        "status": "completed",
        "vaccineCode": {
            "coding": [
                {
                    "system": "http://hl7.org/fhir/sid/cvx",
                    "code": "140",
                    "display": "Influenza, split virus, trivalent, PF",
                }
            ],
            "text": "Influenza, split virus, trivalent, PF",
        },
        "patient": {"reference": _PATIENT_URN},
        "occurrenceDateTime": "2016-11-03T11:38:04-04:00",
    }
    resource.update(overrides)
    return resource


class TestHappyPath:
    def test_cvx_code_extracted(self) -> None:
        row, issues = extract_immunization(_immunization(), _REFMAP, _POINTER)
        assert issues == []
        assert row is not None
        assert row.immunization_id == "imm-1"
        assert row.patient_id == "p1"
        assert row.code == "140"
        assert row.code_system == "CVX"
        assert row.code_display == "Influenza, split virus, trivalent, PF"
        assert row.occurrence_date == date(2016, 11, 3)

    def test_evening_offset_keeps_local_calendar_date(self) -> None:
        # 23:38 at -04:00 is already Nov 4 in UTC; the local date must stay Nov 3.
        resource = _immunization(occurrenceDateTime="2016-11-03T23:38:04-04:00")
        row, issues = extract_immunization(resource, _REFMAP, _POINTER)
        assert issues == []
        assert row is not None
        assert row.occurrence_date == date(2016, 11, 3)

    def test_non_cvx_coding_falls_back_to_first_with_code(self) -> None:
        resource = _immunization(
            vaccineCode={"coding": [{"system": "http://snomed.info/sct", "code": "871895005"}]}
        )
        row, issues = extract_immunization(resource, _REFMAP, _POINTER)
        assert issues == []
        assert row is not None
        assert row.code == "871895005"
        assert row.code_system == "SNOMED"
        assert row.code_display is None

    def test_relative_patient_reference_resolves(self) -> None:
        resource = _immunization(patient={"reference": "Patient/p1"})
        row, issues = extract_immunization(resource, _REFMAP, _POINTER)
        assert issues == []
        assert row is not None
        assert row.patient_id == "p1"


class TestStatusGate:
    def test_non_completed_dropped_silently(self) -> None:
        resource = _immunization(status="not-done")
        assert extract_immunization(resource, _REFMAP, _POINTER) == (None, [])

    def test_missing_status_dropped_silently(self) -> None:
        resource = _immunization()
        del resource["status"]
        assert extract_immunization(resource, _REFMAP, _POINTER) == (None, [])


class TestDrops:
    def test_missing_id_drops_with_issue(self) -> None:
        resource = _immunization()
        del resource["id"]
        row, issues = extract_immunization(resource, _REFMAP, _POINTER)
        assert row is None
        assert [(i.code, i.json_pointer) for i in issues] == [
            ("immunization_missing_id", f"{_POINTER}/id")
        ]

    def test_dangling_patient_reference(self) -> None:
        resource = _immunization(patient={"reference": "urn:uuid:not-in-bundle"})
        row, issues = extract_immunization(resource, _REFMAP, _POINTER)
        assert row is None
        assert [(i.code, i.json_pointer) for i in issues] == [
            ("dangling_subject_reference", f"{_POINTER}/patient")
        ]

    def test_reference_to_non_patient_is_dangling(self) -> None:
        refmap = {_PATIENT_URN: ("Practitioner", "p1")}
        row, issues = extract_immunization(_immunization(), refmap, _POINTER)
        assert row is None
        assert issues[0].code == "dangling_subject_reference"

    def test_missing_patient_field_is_dangling(self) -> None:
        resource = _immunization()
        del resource["patient"]
        row, issues = extract_immunization(resource, _REFMAP, _POINTER)
        assert row is None
        assert issues[0].code == "dangling_subject_reference"

    def test_missing_vaccine_code_element(self) -> None:
        resource = _immunization()
        del resource["vaccineCode"]
        row, issues = extract_immunization(resource, _REFMAP, _POINTER)
        assert row is None
        assert [(i.code, i.json_pointer) for i in issues] == [
            ("immunization_missing_code", f"{_POINTER}/vaccineCode")
        ]

    def test_codings_without_code_drop(self) -> None:
        resource = _immunization(vaccineCode={"coding": [{"system": "http://loinc.org"}]})
        row, issues = extract_immunization(resource, _REFMAP, _POINTER)
        assert row is None
        assert issues[0].code == "immunization_missing_code"

    def test_missing_occurrence_drops_with_issue(self) -> None:
        resource = _immunization()
        del resource["occurrenceDateTime"]
        row, issues = extract_immunization(resource, _REFMAP, _POINTER)
        assert row is None
        assert [(i.code, i.json_pointer) for i in issues] == [
            ("immunization_missing_occurrence", f"{_POINTER}/occurrenceDateTime")
        ]

    def test_garbage_occurrence_drops_with_issue(self) -> None:
        resource = _immunization(occurrenceDateTime="last Tuesday")
        row, issues = extract_immunization(resource, _REFMAP, _POINTER)
        assert row is None
        assert issues[0].code == "immunization_missing_occurrence"
