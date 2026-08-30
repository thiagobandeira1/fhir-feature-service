"""Unit tests for the Encounter extractor — class normalization and the period.start rule."""

from datetime import UTC, date, datetime
from typing import Any

from fhir_features.fhir.bundle import RefMap
from fhir_features.fhir.extractors.encounter import extract_encounter

_REFMAP: RefMap = {"urn:uuid:pat-1": ("Patient", "pat-1")}
_POINTER = "/entry/3/resource"


def _encounter(**overrides: Any) -> dict[str, Any]:
    """A minimal Synthea-shaped Encounter; overrides replace top-level fields."""
    resource: dict[str, Any] = {
        "resourceType": "Encounter",
        "id": "enc-1",
        "status": "finished",
        "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB"},
        "type": [
            {
                "coding": [
                    {
                        "system": "http://snomed.info/sct",
                        "code": "185347001",
                        "display": "Encounter for problem (procedure)",
                    }
                ]
            }
        ],
        "subject": {"reference": "urn:uuid:pat-1"},
        "period": {"start": "2019-06-30T23:15:00-05:00", "end": "2019-07-01T00:05:00-05:00"},
    }
    resource.update(overrides)
    return resource


class TestHappyPath:
    def test_full_row(self) -> None:
        row, issues = extract_encounter(_encounter(), _REFMAP, _POINTER)
        assert issues == []
        assert row is not None
        assert row.encounter_id == "enc-1"
        assert row.patient_id == "pat-1"
        assert row.encounter_class == "AMB"
        assert row.type_code == "185347001"
        assert row.type_system == "SNOMED"
        assert row.type_display == "Encounter for problem (procedure)"
        assert row.start_ts == datetime(2019, 7, 1, 4, 15, tzinfo=UTC)
        assert row.start_date == date(2019, 6, 30)  # local calendar date, NOT the UTC-shifted one
        assert row.date_precision == "second"
        assert row.end_ts == datetime(2019, 7, 1, 5, 5, tzinfo=UTC)

    def test_relative_patient_reference(self) -> None:
        resource = _encounter(subject={"reference": "Patient/pat-9"})
        row, issues = extract_encounter(resource, _REFMAP, _POINTER)
        assert issues == []
        assert row is not None
        assert row.patient_id == "pat-9"

    def test_date_only_start(self) -> None:
        resource = _encounter(period={"start": "2019-06-30"})
        row, issues = extract_encounter(resource, _REFMAP, _POINTER)
        assert issues == []
        assert row is not None
        assert row.start_ts is None
        assert row.start_date == date(2019, 6, 30)
        assert row.date_precision == "day"
        assert row.end_ts is None


class TestEncounterClass:
    def test_synthea_lowercase_ambulatory(self) -> None:
        row, _ = extract_encounter(
            _encounter(**{"class": {"code": "ambulatory"}}), _REFMAP, _POINTER
        )
        assert row is not None
        assert row.encounter_class == "AMB"

    def test_synthea_lowercase_urgentcare(self) -> None:
        row, _ = extract_encounter(
            _encounter(**{"class": {"code": "urgentcare"}}), _REFMAP, _POINTER
        )
        assert row is not None
        assert row.encounter_class == "URGENT"

    def test_actcode_imp(self) -> None:
        resource = _encounter(
            **{
                "class": {
                    "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                    "code": "IMP",
                }
            }
        )
        row, _ = extract_encounter(resource, _REFMAP, _POINTER)
        assert row is not None
        assert row.encounter_class == "IMP"

    def test_unknown_class_goes_to_other(self) -> None:
        row, _ = extract_encounter(
            _encounter(**{"class": {"code": "teleconsult"}}), _REFMAP, _POINTER
        )
        assert row is not None
        assert row.encounter_class == "OTHER"

    def test_missing_class_goes_to_other(self) -> None:
        resource = _encounter()
        del resource["class"]
        row, issues = extract_encounter(resource, _REFMAP, _POINTER)
        assert issues == []
        assert row is not None
        assert row.encounter_class == "OTHER"

    def test_garbage_class_shape_goes_to_other(self) -> None:
        row, _ = extract_encounter(_encounter(**{"class": "AMB"}), _REFMAP, _POINTER)
        assert row is not None
        assert row.encounter_class == "OTHER"


class TestRequiredFields:
    def test_missing_id_drops_row(self) -> None:
        resource = _encounter()
        del resource["id"]
        row, issues = extract_encounter(resource, _REFMAP, _POINTER)
        assert row is None
        assert [i.code for i in issues] == ["encounter_missing_id"]
        assert issues[0].json_pointer == "/entry/3/resource/id"

    def test_missing_period_start_drops_row(self) -> None:
        resource = _encounter(period={"end": "2019-07-01T00:05:00-05:00"})
        row, issues = extract_encounter(resource, _REFMAP, _POINTER)
        assert row is None
        assert [i.code for i in issues] == ["encounter_missing_start"]
        assert issues[0].json_pointer == "/entry/3/resource/period/start"

    def test_missing_period_entirely_drops_row(self) -> None:
        resource = _encounter()
        del resource["period"]
        row, issues = extract_encounter(resource, _REFMAP, _POINTER)
        assert row is None
        assert [i.code for i in issues] == ["encounter_missing_start"]

    def test_garbage_start_drops_row(self) -> None:
        resource = _encounter(period={"start": "not-a-date"})
        row, issues = extract_encounter(resource, _REFMAP, _POINTER)
        assert row is None
        assert [i.code for i in issues] == ["encounter_missing_start"]


class TestSubjectReference:
    def test_dangling_urn_reference_drops_row(self) -> None:
        resource = _encounter(subject={"reference": "urn:uuid:nobody"})
        row, issues = extract_encounter(resource, _REFMAP, _POINTER)
        assert row is None
        assert [i.code for i in issues] == ["dangling_subject_reference"]
        assert issues[0].json_pointer == "/entry/3/resource/subject/reference"

    def test_non_patient_target_drops_row(self) -> None:
        resource = _encounter(subject={"reference": "Practitioner/doc-1"})
        row, issues = extract_encounter(resource, _REFMAP, _POINTER)
        assert row is None
        assert [i.code for i in issues] == ["dangling_subject_reference"]

    def test_missing_subject_drops_row(self) -> None:
        resource = _encounter()
        del resource["subject"]
        row, issues = extract_encounter(resource, _REFMAP, _POINTER)
        assert row is None
        assert [i.code for i in issues] == ["dangling_subject_reference"]


class TestEndDate:
    def test_garbage_end_degrades_to_none_with_issue(self) -> None:
        resource = _encounter(period={"start": "2019-06-30T23:15:00-05:00", "end": "not-a-date"})
        row, issues = extract_encounter(resource, _REFMAP, _POINTER)
        assert row is not None
        assert row.end_ts is None
        assert [i.code for i in issues] == ["unparseable_end_date"]
        assert issues[0].json_pointer == "/entry/3/resource/period/end"

    def test_missing_end_is_fine(self) -> None:
        resource = _encounter(period={"start": "2019-06-30T23:15:00-05:00"})
        row, issues = extract_encounter(resource, _REFMAP, _POINTER)
        assert issues == []
        assert row is not None
        assert row.end_ts is None


class TestTypeCoding:
    def test_missing_type_degrades_to_none(self) -> None:
        resource = _encounter()
        del resource["type"]
        row, issues = extract_encounter(resource, _REFMAP, _POINTER)
        assert issues == []
        assert row is not None
        assert row.type_code is None
        assert row.type_system is None
        assert row.type_display is None

    def test_prefers_snomed_over_other_systems(self) -> None:
        resource = _encounter(
            type=[
                {
                    "coding": [
                        {"system": "http://example.org/local", "code": "L1"},
                        {"system": "http://snomed.info/sct", "code": "185349003"},
                    ]
                }
            ]
        )
        row, _ = extract_encounter(resource, _REFMAP, _POINTER)
        assert row is not None
        assert row.type_code == "185349003"
        assert row.type_system == "SNOMED"

    def test_unmapped_type_system_preserved_in_other(self) -> None:
        resource = _encounter(
            type=[{"coding": [{"system": "http://example.org/local", "code": "L1"}]}]
        )
        row, _ = extract_encounter(resource, _REFMAP, _POINTER)
        assert row is not None
        assert row.type_code == "L1"
        assert row.type_system == "OTHER:http://example.org/local"

    def test_garbage_type_shape_degrades_to_none(self) -> None:
        row, issues = extract_encounter(_encounter(type="checkup"), _REFMAP, _POINTER)
        assert issues == []
        assert row is not None
        assert row.type_code is None
