"""Unit tests for the Condition extractor (Synthea-shaped fragments)."""

from datetime import date
from typing import Any

from fhir_features.fhir.extractors.condition import extract_condition

_POINTER = "/entry/3/resource"

_REFMAP = {
    "urn:uuid:pat-1": ("Patient", "pat-1"),
    "urn:uuid:enc-1": ("Encounter", "enc-1"),
}


def _condition(**overrides: Any) -> dict[str, Any]:
    """A minimal Synthea-shaped Condition; keyword overrides replace top-level fields."""
    resource: dict[str, Any] = {
        "resourceType": "Condition",
        "id": "cond-1",
        "clinicalStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                    "code": "active",
                }
            ]
        },
        "verificationStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                    "code": "confirmed",
                }
            ]
        },
        "code": {
            "coding": [
                {
                    "system": "http://snomed.info/sct",
                    "code": "44054006",
                    "display": "Type 2 diabetes mellitus",
                }
            ],
            "text": "Type 2 diabetes mellitus",
        },
        "subject": {"reference": "urn:uuid:pat-1"},
        "encounter": {"reference": "urn:uuid:enc-1"},
        "onsetDateTime": "2015-03-14T18:45:00-05:00",
        "recordedDate": "2015-03-14T18:45:00-05:00",
    }
    resource.update(overrides)
    return resource


class TestHappyPath:
    def test_full_row(self) -> None:
        row, codings, issues = extract_condition(_condition(), _REFMAP, _POINTER)
        assert issues == []
        assert row is not None
        assert row.condition_id == "cond-1"
        assert row.patient_id == "pat-1"
        assert row.encounter_id == "enc-1"
        assert row.code == "44054006"
        assert row.code_system == "SNOMED"
        assert row.code_display == "Type 2 diabetes mellitus"
        assert row.clinical_status == "active"
        assert row.verification_status == "confirmed"
        assert row.onset_date == date(2015, 3, 14)
        assert row.recorded_date == date(2015, 3, 14)
        assert row.abatement_date is None
        assert row.date_precision == "second"
        assert len(codings) == 1
        assert codings[0].resource_type == "Condition"
        assert codings[0].resource_id == "cond-1"
        assert codings[0].coding_seq == 0
        assert codings[0].code == "44054006"
        assert codings[0].code_system_uri == "http://snomed.info/sct"
        assert codings[0].code_system == "SNOMED"

    def test_abatement_parsed(self) -> None:
        resource = _condition(abatementDateTime="2016-01-02T09:00:00-05:00")
        row, _, issues = extract_condition(resource, _REFMAP, _POINTER)
        assert issues == []
        assert row is not None
        assert row.abatement_date == date(2016, 1, 2)

    def test_evening_offset_keeps_local_calendar_date(self) -> None:
        # 23:30 at -05:00 is the next day in UTC; the local frame must win (ADR-0006).
        resource = _condition(onsetDateTime="2015-03-14T23:30:00-05:00")
        row, _, _ = extract_condition(resource, _REFMAP, _POINTER)
        assert row is not None
        assert row.onset_date == date(2015, 3, 14)

    def test_absent_statuses_degrade_to_none(self) -> None:
        resource = _condition()
        del resource["clinicalStatus"]
        del resource["verificationStatus"]
        row, _, issues = extract_condition(resource, _REFMAP, _POINTER)
        assert issues == []
        assert row is not None
        assert row.clinical_status is None
        assert row.verification_status is None


class TestMissingRequiredFields:
    def test_missing_id_drops_row(self) -> None:
        resource = _condition()
        del resource["id"]
        row, codings, issues = extract_condition(resource, _REFMAP, _POINTER)
        assert row is None
        assert codings == []
        assert [i.code for i in issues] == ["condition_missing_id"]
        assert issues[0].json_pointer == f"{_POINTER}/id"

    def test_missing_code_element_drops_row(self) -> None:
        resource = _condition()
        del resource["code"]
        row, codings, issues = extract_condition(resource, _REFMAP, _POINTER)
        assert row is None
        assert codings == []
        assert [i.code for i in issues] == ["condition_missing_code"]
        assert issues[0].json_pointer == f"{_POINTER}/code"

    def test_codings_without_codes_drop_row(self) -> None:
        resource = _condition(code={"coding": [{"system": "http://snomed.info/sct"}]})
        row, codings, issues = extract_condition(resource, _REFMAP, _POINTER)
        assert row is None
        assert codings == []
        assert [i.code for i in issues] == ["condition_missing_code"]

    def test_missing_onset_and_recorded_drops_row(self) -> None:
        resource = _condition()
        del resource["onsetDateTime"]
        del resource["recordedDate"]
        row, codings, issues = extract_condition(resource, _REFMAP, _POINTER)
        assert row is None
        assert codings == []
        assert [i.code for i in issues] == ["condition_missing_onset"]
        assert issues[0].json_pointer == f"{_POINTER}/onsetDateTime"


class TestSubjectReference:
    def test_dangling_subject_drops_row(self) -> None:
        resource = _condition(subject={"reference": "urn:uuid:not-in-bundle"})
        row, codings, issues = extract_condition(resource, _REFMAP, _POINTER)
        assert row is None
        assert codings == []
        assert [i.code for i in issues] == ["dangling_subject_reference"]
        assert issues[0].json_pointer == f"{_POINTER}/subject/reference"

    def test_subject_resolving_to_non_patient_drops_row(self) -> None:
        resource = _condition(subject={"reference": "urn:uuid:enc-1"})
        row, _, issues = extract_condition(resource, _REFMAP, _POINTER)
        assert row is None
        assert [i.code for i in issues] == ["dangling_subject_reference"]

    def test_missing_subject_drops_row(self) -> None:
        resource = _condition()
        del resource["subject"]
        row, _, issues = extract_condition(resource, _REFMAP, _POINTER)
        assert row is None
        assert [i.code for i in issues] == ["dangling_subject_reference"]

    def test_relative_literal_reference_resolves(self) -> None:
        resource = _condition(subject={"reference": "Patient/pat-9"})
        row, _, issues = extract_condition(resource, _REFMAP, _POINTER)
        assert issues == []
        assert row is not None
        assert row.patient_id == "pat-9"


class TestDates:
    def test_onset_falls_back_to_recorded_with_warning(self) -> None:
        resource = _condition(recordedDate="2018-06-01")
        del resource["onsetDateTime"]
        row, _, issues = extract_condition(resource, _REFMAP, _POINTER)
        assert row is not None
        assert row.onset_date == date(2018, 6, 1)
        assert row.recorded_date == date(2018, 6, 1)
        assert row.date_precision == "day"
        assert [i.code for i in issues] == ["onset_imputed_from_recorded"]
        assert issues[0].json_pointer == f"{_POINTER}/recordedDate"

    def test_garbage_onset_falls_back_to_recorded(self) -> None:
        resource = _condition(onsetDateTime="not-a-date", recordedDate="2018-06-01")
        row, _, issues = extract_condition(resource, _REFMAP, _POINTER)
        assert row is not None
        assert row.onset_date == date(2018, 6, 1)
        assert [i.code for i in issues] == [
            "unparseable_onset_date",
            "onset_imputed_from_recorded",
        ]

    def test_garbage_onset_without_recorded_drops_row(self) -> None:
        resource = _condition(onsetDateTime="14/03/2015")
        del resource["recordedDate"]
        row, codings, issues = extract_condition(resource, _REFMAP, _POINTER)
        assert row is None
        assert codings == []
        assert [i.code for i in issues] == ["unparseable_onset_date", "condition_missing_onset"]

    def test_garbage_abatement_degrades_to_none(self) -> None:
        resource = _condition(abatementDateTime="whenever")
        row, _, issues = extract_condition(resource, _REFMAP, _POINTER)
        assert row is not None
        assert row.abatement_date is None
        assert [i.code for i in issues] == ["unparseable_abatement_date"]
        assert issues[0].json_pointer == f"{_POINTER}/abatementDateTime"

    def test_month_precision_onset(self) -> None:
        resource = _condition(onsetDateTime="2015-03")
        row, _, issues = extract_condition(resource, _REFMAP, _POINTER)
        assert issues == []
        assert row is not None
        assert row.onset_date == date(2015, 3, 1)
        assert row.date_precision == "month"

    def test_garbage_recorded_degrades_to_none(self) -> None:
        resource = _condition(recordedDate="garbage")
        row, _, issues = extract_condition(resource, _REFMAP, _POINTER)
        assert row is not None
        assert row.recorded_date is None
        assert [i.code for i in issues] == ["unparseable_recorded_date"]


class TestEncounterReference:
    def test_dangling_encounter_keeps_row(self) -> None:
        resource = _condition(encounter={"reference": "urn:uuid:not-in-bundle"})
        row, _, issues = extract_condition(resource, _REFMAP, _POINTER)
        assert row is not None
        assert row.encounter_id is None
        assert [i.code for i in issues] == ["dangling_encounter_reference"]
        assert issues[0].json_pointer == f"{_POINTER}/encounter/reference"

    def test_absent_encounter_is_silent(self) -> None:
        resource = _condition()
        del resource["encounter"]
        row, _, issues = extract_condition(resource, _REFMAP, _POINTER)
        assert issues == []
        assert row is not None
        assert row.encounter_id is None


class TestCodings:
    def test_multi_coding_emits_all_rows_and_prefers_snomed(self) -> None:
        resource = _condition(
            code={
                "coding": [
                    {"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "E11.9"},
                    {"system": "http://snomed.info/sct", "code": "44054006", "display": "T2DM"},
                    {"system": "http://example.org/local-codes", "code": "DM2"},
                ]
            }
        )
        row, codings, issues = extract_condition(resource, _REFMAP, _POINTER)
        assert issues == []
        assert row is not None
        # SNOMED wins the primary even though ICD-10-CM appears first.
        assert row.code == "44054006"
        assert row.code_system == "SNOMED"
        assert [(c.coding_seq, c.code) for c in codings] == [
            (0, "E11.9"),
            (1, "44054006"),
            (2, "DM2"),
        ]
        assert [c.code_system_uri for c in codings] == [
            "http://hl7.org/fhir/sid/icd-10-cm",
            "http://snomed.info/sct",
            "http://example.org/local-codes",
        ]
        assert [c.code_system for c in codings] == [
            "ICD10CM",
            "SNOMED",
            "OTHER:http://example.org/local-codes",
        ]

    def test_unmapped_system_preserves_raw_uri_in_other(self) -> None:
        resource = _condition(
            code={"coding": [{"system": "http://example.org/local-codes", "code": "X1"}]}
        )
        row, codings, issues = extract_condition(resource, _REFMAP, _POINTER)
        assert issues == []
        assert row is not None
        assert row.code_system == "OTHER:http://example.org/local-codes"
        assert codings[0].code_system == "OTHER:http://example.org/local-codes"
        assert codings[0].code_system_uri == "http://example.org/local-codes"

    def test_coding_without_code_keeps_enumeration_order(self) -> None:
        resource = _condition(
            code={
                "coding": [
                    {"system": "http://example.org/x"},  # no code -> no side-table row
                    {"system": "http://snomed.info/sct", "code": "44054006"},
                ]
            }
        )
        row, codings, issues = extract_condition(resource, _REFMAP, _POINTER)
        assert issues == []
        assert row is not None
        assert [(c.coding_seq, c.code) for c in codings] == [(1, "44054006")]
