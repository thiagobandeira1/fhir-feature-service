"""Unit tests for the Procedure extractor on handwritten Synthea-shaped fragments."""

from datetime import date
from typing import Any

from fhir_features.fhir.bundle import RefMap
from fhir_features.fhir.extractors.procedure import extract_procedure

_POINTER = "/entry/3/resource"

_REFMAP: RefMap = {
    "urn:uuid:pat-1": ("Patient", "pat-1"),
    "urn:uuid:enc-1": ("Encounter", "enc-1"),
}


def _procedure(**overrides: Any) -> dict[str, Any]:
    """A completed Synthea-shaped Procedure using the performedPeriod form."""
    base: dict[str, Any] = {
        "resourceType": "Procedure",
        "id": "proc-1",
        "status": "completed",
        "code": {
            "coding": [
                {
                    "system": "http://snomed.info/sct",
                    "code": "710824005",
                    "display": "Assessment of health and social care needs (procedure)",
                }
            ],
            "text": "Assessment of health and social care needs (procedure)",
        },
        "subject": {"reference": "urn:uuid:pat-1"},
        "encounter": {"reference": "urn:uuid:enc-1"},
        "performedPeriod": {
            "start": "2016-11-03T11:38:04-04:00",
            "end": "2016-11-03T12:33:09-04:00",
        },
    }
    base.update(overrides)
    return base


class TestHappyPath:
    def test_performed_period_path(self) -> None:
        row, codings, issues = extract_procedure(_procedure(), _REFMAP, _POINTER)
        assert issues == []
        assert row is not None
        assert row.procedure_id == "proc-1"
        assert row.patient_id == "pat-1"
        assert row.encounter_id == "enc-1"
        assert row.code == "710824005"
        assert row.code_system == "SNOMED"
        assert row.code_display == "Assessment of health and social care needs (procedure)"
        assert row.performed_date == date(2016, 11, 3)
        assert row.performed_end_date == date(2016, 11, 3)
        assert row.date_precision == "second"
        assert row.status == "completed"
        assert len(codings) == 1

    def test_performed_datetime_path(self) -> None:
        resource = _procedure(performedDateTime="2019-05-11T09:00:00-04:00")
        del resource["performedPeriod"]
        row, _, issues = extract_procedure(resource, _REFMAP, _POINTER)
        assert issues == []
        assert row is not None
        assert row.performed_date == date(2019, 5, 11)
        assert row.performed_end_date is None
        assert row.date_precision == "second"

    def test_performed_datetime_wins_over_period(self) -> None:
        resource = _procedure(performedDateTime="2019-05-11")
        row, _, issues = extract_procedure(resource, _REFMAP, _POINTER)
        assert issues == []
        assert row is not None
        assert row.performed_date == date(2019, 5, 11)
        assert row.date_precision == "day"
        # The period end still fills the optional column.
        assert row.performed_end_date == date(2016, 11, 3)

    def test_evening_negative_offset_keeps_local_calendar_date(self) -> None:
        resource = _procedure(
            performedPeriod={"start": "2016-11-03T23:15:00-04:00"},
        )
        row, _, _ = extract_procedure(resource, _REFMAP, _POINTER)
        assert row is not None
        assert row.performed_date == date(2016, 11, 3)  # NOT Nov 4 (the UTC day)

    def test_garbage_performed_datetime_falls_back_to_period_start(self) -> None:
        resource = _procedure(performedDateTime="not-a-date")
        row, _, issues = extract_procedure(resource, _REFMAP, _POINTER)
        assert issues == []
        assert row is not None
        assert row.performed_date == date(2016, 11, 3)


class TestStatusFilter:
    def test_non_completed_silently_dropped(self) -> None:
        for status in ("in-progress", "not-done", "stopped", "unknown"):
            resource = _procedure(status=status)
            assert extract_procedure(resource, _REFMAP, _POINTER) == (None, [], [])

    def test_missing_status_silently_dropped(self) -> None:
        resource = _procedure()
        del resource["status"]
        assert extract_procedure(resource, _REFMAP, _POINTER) == (None, [], [])


class TestRequiredFields:
    def test_missing_id_drops_with_issue(self) -> None:
        resource = _procedure()
        del resource["id"]
        row, codings, issues = extract_procedure(resource, _REFMAP, _POINTER)
        assert row is None
        assert codings == []
        assert [i.code for i in issues] == ["procedure_missing_id"]
        assert issues[0].json_pointer == f"{_POINTER}/id"

    def test_missing_code_drops_with_issue(self) -> None:
        resource = _procedure(code={"text": "no codings here"})
        row, codings, issues = extract_procedure(resource, _REFMAP, _POINTER)
        assert row is None
        assert codings == []
        assert [i.code for i in issues] == ["procedure_missing_code"]
        assert issues[0].json_pointer == f"{_POINTER}/code"

    def test_codings_without_code_drop_with_issue(self) -> None:
        resource = _procedure(code={"coding": [{"system": "http://snomed.info/sct"}]})
        row, _, issues = extract_procedure(resource, _REFMAP, _POINTER)
        assert row is None
        assert [i.code for i in issues] == ["procedure_missing_code"]

    def test_dangling_subject_reference(self) -> None:
        resource = _procedure(subject={"reference": "urn:uuid:not-in-bundle"})
        row, codings, issues = extract_procedure(resource, _REFMAP, _POINTER)
        assert row is None
        assert codings == []
        assert [i.code for i in issues] == ["dangling_subject_reference"]
        assert issues[0].json_pointer == f"{_POINTER}/subject/reference"

    def test_subject_resolving_to_non_patient_is_dangling(self) -> None:
        resource = _procedure(subject={"reference": "Group/g-1"})
        row, _, issues = extract_procedure(resource, _REFMAP, _POINTER)
        assert row is None
        assert [i.code for i in issues] == ["dangling_subject_reference"]

    def test_garbage_performed_drops_with_issue(self) -> None:
        resource = _procedure(performedDateTime="not-a-date")
        del resource["performedPeriod"]
        row, codings, issues = extract_procedure(resource, _REFMAP, _POINTER)
        assert row is None
        assert codings == []
        assert [i.code for i in issues] == ["procedure_missing_performed"]
        assert issues[0].json_pointer == f"{_POINTER}/performedDateTime"

    def test_missing_performed_drops_with_issue(self) -> None:
        resource = _procedure()
        del resource["performedPeriod"]
        row, _, issues = extract_procedure(resource, _REFMAP, _POINTER)
        assert row is None
        assert [i.code for i in issues] == ["procedure_missing_performed"]
        assert issues[0].json_pointer.startswith(_POINTER)


class TestCodingSideRows:
    def test_all_codings_emitted_with_raw_uri_preserved(self) -> None:
        resource = _procedure(
            code={
                "coding": [
                    {
                        "system": "http://example.org/local",
                        "code": "LOCAL-1",
                        "display": "Local label",
                    },
                    {
                        "system": "http://snomed.info/sct",
                        "code": "73761001",
                        "display": "Colonoscopy",
                    },
                    {"system": "http://snomed.info/sct"},  # no code -> no side row
                ]
            }
        )
        row, codings, issues = extract_procedure(resource, _REFMAP, _POINTER)
        assert issues == []
        assert row is not None
        # Primary preference picks SNOMED even though it is listed second.
        assert row.code == "73761001"
        assert row.code_system == "SNOMED"
        assert [(c.coding_seq, c.code) for c in codings] == [(0, "LOCAL-1"), (1, "73761001")]
        assert all(c.resource_type == "Procedure" and c.resource_id == "proc-1" for c in codings)
        assert codings[0].code_system_uri == "http://example.org/local"
        assert codings[0].code_system == "OTHER:http://example.org/local"
        assert codings[1].code_system_uri == "http://snomed.info/sct"
        assert codings[1].code_system == "SNOMED"
        assert codings[1].display == "Colonoscopy"

    def test_cpt_preferred_when_no_snomed(self) -> None:
        resource = _procedure(
            code={
                "coding": [
                    {"system": "http://example.org/local", "code": "LOCAL-1"},
                    {"system": "http://www.ama-assn.org/go/cpt", "code": "45378"},
                ]
            }
        )
        row, codings, _ = extract_procedure(resource, _REFMAP, _POINTER)
        assert row is not None
        assert row.code == "45378"
        assert row.code_system == "CPT"
        assert len(codings) == 2


class TestOptionalDegradation:
    def test_missing_encounter_is_none_without_issue(self) -> None:
        resource = _procedure()
        del resource["encounter"]
        row, _, issues = extract_procedure(resource, _REFMAP, _POINTER)
        assert row is not None
        assert row.encounter_id is None
        assert issues == []

    def test_dangling_encounter_degrades_with_issue(self) -> None:
        resource = _procedure(encounter={"reference": "urn:uuid:not-in-bundle"})
        row, _, issues = extract_procedure(resource, _REFMAP, _POINTER)
        assert row is not None
        assert row.encounter_id is None
        assert [i.code for i in issues] == ["dangling_encounter_reference"]
        assert issues[0].json_pointer == f"{_POINTER}/encounter/reference"

    def test_garbage_period_end_degrades_with_issue(self) -> None:
        resource = _procedure(
            performedPeriod={"start": "2016-11-03T11:38:04-04:00", "end": "garbage"}
        )
        row, _, issues = extract_procedure(resource, _REFMAP, _POINTER)
        assert row is not None
        assert row.performed_date == date(2016, 11, 3)
        assert row.performed_end_date is None
        assert [i.code for i in issues] == ["unparseable_performed_end"]
        assert issues[0].json_pointer == f"{_POINTER}/performedPeriod/end"
