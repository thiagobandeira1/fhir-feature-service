"""Unit tests for code-system normalization and coding selection."""

from fhir_features.canonical.codes import (
    Coding,
    normalize_encounter_class,
    normalize_system,
    pick_primary_coding,
)


class TestNormalizeSystem:
    def test_known_systems(self) -> None:
        assert normalize_system("http://snomed.info/sct") == "SNOMED"
        assert normalize_system("http://loinc.org") == "LOINC"
        assert normalize_system("http://www.nlm.nih.gov/research/umls/rxnorm") == "RXNORM"
        assert normalize_system("http://hl7.org/fhir/sid/cvx") == "CVX"
        assert normalize_system("http://hl7.org/fhir/sid/icd-10-cm") == "ICD10CM"

    def test_unmapped_uri_preserved_in_other(self) -> None:
        assert normalize_system("http://example.org/custom") == "OTHER:http://example.org/custom"

    def test_missing(self) -> None:
        assert normalize_system(None) == "OTHER:"


class TestEncounterClass:
    def test_actcode_tokens(self) -> None:
        assert normalize_encounter_class("AMB") == "AMB"
        assert normalize_encounter_class("IMP") == "IMP"
        assert normalize_encounter_class("EMER") == "EMER"

    def test_synthea_lowercase_strings(self) -> None:
        assert normalize_encounter_class("ambulatory") == "AMB"
        assert normalize_encounter_class("wellness") == "WELLNESS"
        assert normalize_encounter_class("emergency") == "EMER"
        assert normalize_encounter_class("urgentcare") == "URGENT"
        assert normalize_encounter_class("inpatient") == "IMP"

    def test_unknown_goes_to_other_bucket(self) -> None:
        assert normalize_encounter_class("teleconsult") == "OTHER"
        assert normalize_encounter_class(None) == "OTHER"
        assert normalize_encounter_class("") == "OTHER"


class TestPickPrimaryCoding:
    def test_prefers_ordered_systems(self) -> None:
        codings: list[Coding] = [
            {"system": "http://example.org/x", "code": "X1"},
            {"system": "http://snomed.info/sct", "code": "44054006", "display": "T2DM"},
        ]
        picked = pick_primary_coding(codings, prefer=("SNOMED",))
        assert picked is not None
        assert picked["code"] == "44054006"

    def test_falls_back_to_first_with_code(self) -> None:
        codings: list[Coding] = [
            {"system": "http://example.org/x"},  # no code
            {"system": "http://example.org/y", "code": "Y1"},
        ]
        picked = pick_primary_coding(codings, prefer=("SNOMED", "LOINC"))
        assert picked is not None
        assert picked["code"] == "Y1"

    def test_empty(self) -> None:
        assert pick_primary_coding([], prefer=("SNOMED",)) is None
