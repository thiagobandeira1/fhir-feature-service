"""Unit tests for the Patient extractor over inline Synthea-shaped fragments."""

from datetime import date
from typing import Any

from fhir_features.canonical.models import ParseIssue
from fhir_features.fhir.extractors.patient import extract_patient

POINTER = "/entry/0/resource"


def synthea_patient() -> dict[str, Any]:
    """A full Synthea-shaped Patient: US Core extensions, address, deceasedDateTime."""
    return {
        "resourceType": "Patient",
        "id": "939eea26-a679-2564-5cf9-c0fd557beefc",
        "meta": {"profile": ["http://hl7.org/fhir/us/core/StructureDefinition/us-core-patient"]},
        "extension": [
            {
                "url": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race",
                "extension": [
                    {
                        "url": "ombCategory",
                        "valueCoding": {
                            "system": "urn:oid:2.16.840.1.113883.6.238",
                            "code": "2106-3",
                            "display": "White",
                        },
                    },
                    {"url": "text", "valueString": "White"},
                ],
            },
            {
                "url": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-ethnicity",
                "extension": [
                    {
                        "url": "ombCategory",
                        "valueCoding": {
                            "system": "urn:oid:2.16.840.1.113883.6.238",
                            "code": "2186-5",
                            "display": "Not Hispanic or Latino",
                        },
                    },
                    {"url": "text", "valueString": "Not Hispanic or Latino"},
                ],
            },
            {
                "url": "http://hl7.org/fhir/StructureDefinition/patient-mothersMaidenName",
                "valueString": "Ester635 Gleichner915",
            },
            {
                "url": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-birthsex",
                "valueCode": "M",
            },
        ],
        "gender": "male",
        "birthDate": "1950-08-03",
        "deceasedDateTime": "2019-06-30T23:15:00-05:00",
        "address": [
            {
                "extension": [
                    {
                        "url": "http://hl7.org/fhir/StructureDefinition/geolocation",
                        "extension": [
                            {"url": "latitude", "valueDecimal": 27.845842669792432},
                            {"url": "longitude", "valueDecimal": -82.17740023344743},
                        ],
                    }
                ],
                "line": ["873 Conroy Corner Unit 30"],
                "city": "Valrico",
                "state": "FL",
                "postalCode": "33594",
                "country": "US",
            }
        ],
        "maritalStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/v3-MaritalStatus",
                    "code": "S",
                    "display": "Never Married",
                }
            ],
            "text": "Never Married",
        },
        "multipleBirthBoolean": False,
    }


class TestHappyPath:
    def test_full_synthea_patient_extracts_all_fields(self) -> None:
        row, issues = extract_patient(synthea_patient(), POINTER)
        assert issues == []
        assert row is not None
        assert row.patient_id == "939eea26-a679-2564-5cf9-c0fd557beefc"
        assert row.birth_date == date(1950, 8, 3)
        # 11:15 PM at -05:00 is next-day UTC — the death DATE must stay in the local frame.
        assert row.death_date == date(2019, 6, 30)
        assert row.sex == "male"
        assert row.race == "White"
        assert row.ethnicity == "Not Hispanic or Latino"
        assert row.city == "Valrico"
        assert row.state == "FL"
        assert row.postal_code == "33594"

    def test_alive_patient_has_no_death_date(self) -> None:
        resource = synthea_patient()
        del resource["deceasedDateTime"]
        row, issues = extract_patient(resource, POINTER)
        assert issues == []
        assert row is not None
        assert row.death_date is None


class TestRequiredFields:
    def test_missing_id_drops_row_with_issue(self) -> None:
        resource = synthea_patient()
        del resource["id"]
        row, issues = extract_patient(resource, POINTER)
        assert row is None
        assert issues == [ParseIssue(code="patient_missing_id", json_pointer=f"{POINTER}/id")]

    def test_non_string_id_drops_row_with_issue(self) -> None:
        resource = synthea_patient()
        resource["id"] = 12345
        row, issues = extract_patient(resource, POINTER)
        assert row is None
        assert issues == [ParseIssue(code="patient_missing_id", json_pointer=f"{POINTER}/id")]


class TestDegradedFields:
    def test_garbage_birth_date_keeps_row_with_issue(self) -> None:
        resource = synthea_patient()
        resource["birthDate"] = "not-a-date"
        row, issues = extract_patient(resource, POINTER)
        assert row is not None
        assert row.birth_date is None
        assert issues == [
            ParseIssue(code="unparseable_birth_date", json_pointer=f"{POINTER}/birthDate")
        ]

    def test_garbage_death_date_keeps_row_with_issue(self) -> None:
        resource = synthea_patient()
        resource["deceasedDateTime"] = "yesterday"
        row, issues = extract_patient(resource, POINTER)
        assert row is not None
        assert row.death_date is None
        assert issues == [
            ParseIssue(code="unparseable_death_date", json_pointer=f"{POINTER}/deceasedDateTime")
        ]

    def test_unknown_gender_string_becomes_unknown(self) -> None:
        resource = synthea_patient()
        resource["gender"] = "M"  # HL7 v2 token, not a FHIR AdministrativeGender code
        row, issues = extract_patient(resource, POINTER)
        assert issues == []
        assert row is not None
        assert row.sex == "unknown"

    def test_missing_gender_becomes_unknown(self) -> None:
        resource = synthea_patient()
        del resource["gender"]
        row, _ = extract_patient(resource, POINTER)
        assert row is not None
        assert row.sex == "unknown"

    def test_no_address_yields_none_fields(self) -> None:
        resource = synthea_patient()
        del resource["address"]
        row, issues = extract_patient(resource, POINTER)
        assert issues == []
        assert row is not None
        assert row.city is None
        assert row.state is None
        assert row.postal_code is None

    def test_non_mapping_address_entry_yields_none_fields(self) -> None:
        resource = synthea_patient()
        resource["address"] = ["not-an-object"]
        row, issues = extract_patient(resource, POINTER)
        assert issues == []
        assert row is not None
        assert row.city is None
        assert row.state is None
        assert row.postal_code is None

    def test_missing_extensions_yield_none_race_ethnicity(self) -> None:
        resource = synthea_patient()
        del resource["extension"]
        row, issues = extract_patient(resource, POINTER)
        assert issues == []
        assert row is not None
        assert row.race is None
        assert row.ethnicity is None
