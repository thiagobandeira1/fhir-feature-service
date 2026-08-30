"""Unit tests for the MedicationRequest extractor on handwritten Synthea-shaped fragments."""

from datetime import date
from typing import Any

from fhir_features.fhir.bundle import RefMap
from fhir_features.fhir.extractors.medication_request import extract_medication_request

_POINTER = "/entry/7/resource"

_REFMAP: RefMap = {
    "urn:uuid:pat-1": ("Patient", "pat-1"),
    "urn:uuid:enc-1": ("Encounter", "enc-1"),
}

_RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"


def _resource(**overrides: Any) -> dict[str, Any]:
    """A minimal Synthea-shaped MedicationRequest; tests mutate/delete fields as needed."""
    base: dict[str, Any] = {
        "resourceType": "MedicationRequest",
        "id": "mr-1",
        "status": "active",
        "intent": "order",
        "medicationCodeableConcept": {
            "coding": [
                {"system": _RXNORM, "code": "308136", "display": "amLODIPine 2.5 MG Oral Tablet"}
            ],
            "text": "amLODIPine 2.5 MG Oral Tablet",
        },
        "subject": {"reference": "urn:uuid:pat-1"},
        "encounter": {"reference": "urn:uuid:enc-1"},
        "authoredOn": "2015-10-29T23:38:04-04:00",
    }
    base.update(overrides)
    return base


class TestHappyPath:
    def test_full_row(self) -> None:
        row, issues = extract_medication_request(_resource(), _REFMAP, _POINTER)
        assert issues == []
        assert row is not None
        assert row.medication_request_id == "mr-1"
        assert row.patient_id == "pat-1"
        assert row.encounter_id == "enc-1"
        assert row.code == "308136"
        assert row.code_system == "RXNORM"
        assert row.code_display == "amLODIPine 2.5 MG Oral Tablet"
        # 11:38 PM at -04:00 is next-day UTC — the DATE must stay in the source-local frame.
        assert row.authored_date == date(2015, 10, 29)
        assert row.date_precision == "second"

    def test_relative_subject_reference(self) -> None:
        resource = _resource(subject={"reference": "Patient/pat-9"})
        row, issues = extract_medication_request(resource, _REFMAP, _POINTER)
        assert issues == []
        assert row is not None
        assert row.patient_id == "pat-9"

    def test_day_precision_authored(self) -> None:
        row, issues = extract_medication_request(
            _resource(authoredOn="2015-10-29"), _REFMAP, _POINTER
        )
        assert issues == []
        assert row is not None
        assert row.authored_date == date(2015, 10, 29)
        assert row.date_precision == "day"


class TestCodeSelection:
    def test_rxnorm_preferred_among_multiple_codings(self) -> None:
        concept = {
            "coding": [
                {"system": "http://snomed.info/sct", "code": "999", "display": "SNOMED med"},
                {"system": _RXNORM, "code": "308136", "display": "amLODIPine"},
            ]
        }
        row, issues = extract_medication_request(
            _resource(medicationCodeableConcept=concept), _REFMAP, _POINTER
        )
        assert issues == []
        assert row is not None
        assert row.code == "308136"
        assert row.code_system == "RXNORM"

    def test_falls_back_to_first_coded_when_no_rxnorm(self) -> None:
        concept = {"coding": [{"system": "http://example.org/local", "code": "L1"}]}
        row, issues = extract_medication_request(
            _resource(medicationCodeableConcept=concept), _REFMAP, _POINTER
        )
        assert issues == []
        assert row is not None
        assert row.code == "L1"
        assert row.code_system == "OTHER:http://example.org/local"
        assert row.code_display is None

    def test_missing_concept_drops_with_issue(self) -> None:
        resource = _resource()
        del resource["medicationCodeableConcept"]
        row, issues = extract_medication_request(resource, _REFMAP, _POINTER)
        assert row is None
        assert [i.code for i in issues] == ["medication_missing_code"]
        assert issues[0].json_pointer == f"{_POINTER}/medicationCodeableConcept"

    def test_codings_without_codes_drop_with_issue(self) -> None:
        concept = {"coding": [{"system": _RXNORM, "display": "no code here"}]}
        row, issues = extract_medication_request(
            _resource(medicationCodeableConcept=concept), _REFMAP, _POINTER
        )
        assert row is None
        assert [i.code for i in issues] == ["medication_missing_code"]


class TestRequiredFields:
    def test_missing_id_drops(self) -> None:
        resource = _resource()
        del resource["id"]
        row, issues = extract_medication_request(resource, _REFMAP, _POINTER)
        assert row is None
        assert [i.code for i in issues] == ["medication_missing_id"]
        assert issues[0].json_pointer == f"{_POINTER}/id"

    def test_missing_authored_drops(self) -> None:
        resource = _resource()
        del resource["authoredOn"]
        row, issues = extract_medication_request(resource, _REFMAP, _POINTER)
        assert row is None
        assert [i.code for i in issues] == ["medication_missing_authored"]
        assert issues[0].json_pointer == f"{_POINTER}/authoredOn"

    def test_garbage_authored_drops(self) -> None:
        row, issues = extract_medication_request(
            _resource(authoredOn="not-a-date"), _REFMAP, _POINTER
        )
        assert row is None
        assert [i.code for i in issues] == ["medication_missing_authored"]


class TestSubjectReference:
    def test_dangling_subject_drops(self) -> None:
        resource = _resource(subject={"reference": "urn:uuid:nobody"})
        row, issues = extract_medication_request(resource, _REFMAP, _POINTER)
        assert row is None
        assert [i.code for i in issues] == ["dangling_subject_reference"]
        assert issues[0].json_pointer == f"{_POINTER}/subject/reference"

    def test_missing_subject_drops(self) -> None:
        resource = _resource()
        del resource["subject"]
        row, issues = extract_medication_request(resource, _REFMAP, _POINTER)
        assert row is None
        assert [i.code for i in issues] == ["dangling_subject_reference"]

    def test_subject_resolving_to_non_patient_drops(self) -> None:
        resource = _resource(subject={"reference": "urn:uuid:enc-1"})
        row, issues = extract_medication_request(resource, _REFMAP, _POINTER)
        assert row is None
        assert [i.code for i in issues] == ["dangling_subject_reference"]


class TestEncounterReference:
    def test_dangling_encounter_keeps_row_with_issue(self) -> None:
        resource = _resource(encounter={"reference": "urn:uuid:no-such-encounter"})
        row, issues = extract_medication_request(resource, _REFMAP, _POINTER)
        assert row is not None
        assert row.encounter_id is None
        assert [i.code for i in issues] == ["dangling_encounter_reference"]
        assert issues[0].json_pointer == f"{_POINTER}/encounter/reference"

    def test_absent_encounter_is_none_without_issue(self) -> None:
        resource = _resource()
        del resource["encounter"]
        row, issues = extract_medication_request(resource, _REFMAP, _POINTER)
        assert issues == []
        assert row is not None
        assert row.encounter_id is None


class TestDisplayOnlyFields:
    def test_status_and_intent_stored_verbatim(self) -> None:
        row, issues = extract_medication_request(
            _resource(status="stopped", intent="plan"), _REFMAP, _POINTER
        )
        assert issues == []
        assert row is not None
        assert row.status == "stopped"  # verbatim, never normalized — display-only per SPEC
        assert row.intent == "plan"

    def test_absent_status_and_intent_are_none(self) -> None:
        resource = _resource()
        del resource["status"]
        del resource["intent"]
        row, issues = extract_medication_request(resource, _REFMAP, _POINTER)
        assert issues == []
        assert row is not None
        assert row.status is None
        assert row.intent is None

    def test_non_string_status_degrades_to_none(self) -> None:
        row, issues = extract_medication_request(_resource(status=42), _REFMAP, _POINTER)
        assert issues == []
        assert row is not None
        assert row.status is None
