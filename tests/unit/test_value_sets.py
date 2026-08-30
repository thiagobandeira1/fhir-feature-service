"""Unit tests for the committed value-set JSON files and their loader."""

import json
from pathlib import Path

import pytest

from fhir_features.features.value_sets import (
    ValueSetBundle,
    ValueSetMember,
    _load_from,
    load_value_sets,
)

EXPECTED_VALUE_SET_IDS = {
    "diabetes_snomed",
    "hypertension_snomed",
    "ascvd_snomed",
    "ckd_snomed",
    "chf_snomed",
    "copd_snomed",
    "statin_rxnorm",
    "hba1c_loinc",
    "bp_loinc",
    "bmi_loinc",
    "tobacco_status_loinc",
    "fobt_fit_loinc",
    "mammogram_proc",
    "colonoscopy_proc",
    "retinal_exam_proc",
    "flu_vaccine_cvx",
}


@pytest.fixture(scope="module")
def bundle() -> ValueSetBundle:
    return load_value_sets()


def _codes(bundle: ValueSetBundle, value_set_id: str) -> set[str]:
    return {m.code for m in bundle.members if m.value_set_id == value_set_id}


class TestCommittedValueSets:
    def test_every_expected_set_exists_and_is_non_empty(self, bundle: ValueSetBundle) -> None:
        present = {m.value_set_id for m in bundle.members}
        assert present == EXPECTED_VALUE_SET_IDS
        for value_set_id in EXPECTED_VALUE_SET_IDS:
            assert _codes(bundle, value_set_id), f"{value_set_id} is empty"

    def test_version_is_consistent_calver(self, bundle: ValueSetBundle) -> None:
        assert bundle.version == "2026.08"

    def test_no_duplicate_members(self, bundle: ValueSetBundle) -> None:
        keys = [(m.value_set_id, m.code_system, m.code) for m in bundle.members]
        assert len(keys) == len(set(keys))

    def test_each_set_uses_one_code_system(self, bundle: ValueSetBundle) -> None:
        systems: dict[str, set[str]] = {}
        for m in bundle.members:
            systems.setdefault(m.value_set_id, set()).add(m.code_system)
        assert all(len(s) == 1 for s in systems.values())

    def test_hba1c_spot_check(self, bundle: ValueSetBundle) -> None:
        assert "4548-4" in _codes(bundle, "hba1c_loinc")

    def test_bp_panel_and_components(self, bundle: ValueSetBundle) -> None:
        assert {"85354-9", "8480-6", "8462-4"} <= _codes(bundle, "bp_loinc")

    def test_statins_cover_at_least_three_distinct_agents(self, bundle: ValueSetBundle) -> None:
        displays = [m.display.lower() for m in bundle.members if m.value_set_id == "statin_rxnorm"]
        agents = {
            agent
            for agent in (
                "simvastatin",
                "atorvastatin",
                "rosuvastatin",
                "pravastatin",
                "lovastatin",
                "fluvastatin",
                "pitavastatin",
            )
            if any(agent in d for d in displays)
        }
        assert len(agents) >= 3

    def test_diabetes_excludes_prediabetes_and_gestational(self, bundle: ValueSetBundle) -> None:
        for m in bundle.members:
            if m.value_set_id == "diabetes_snomed":
                assert "prediabetes" not in m.display.lower()
                assert "gestation" not in m.display.lower()


def _write_value_set_file(path: Path, version: str, value_set_id: str, code: str) -> None:
    payload = {
        "valuesets_version": version,
        "value_sets": {
            value_set_id: {
                "code_system": "SNOMED",
                "codes": [{"code": code, "display": "Example (disorder)"}],
            }
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


class TestLoaderValidation:
    def test_merges_multiple_files(self, tmp_path: Path) -> None:
        _write_value_set_file(tmp_path / "a.json", "2026.08", "set_a", "1")
        _write_value_set_file(tmp_path / "b.json", "2026.08", "set_b", "2")
        merged = _load_from(tmp_path)
        assert merged.version == "2026.08"
        assert {m.value_set_id for m in merged.members} == {"set_a", "set_b"}
        assert merged.members[0] == ValueSetMember(
            value_set_id="set_a", code_system="SNOMED", code="1", display="Example (disorder)"
        )

    def test_version_mismatch_across_files_raises(self, tmp_path: Path) -> None:
        _write_value_set_file(tmp_path / "a.json", "2026.08", "set_a", "1")
        _write_value_set_file(tmp_path / "b.json", "2026.09", "set_b", "2")
        with pytest.raises(ValueError, match="valuesets_version"):
            _load_from(tmp_path)

    def test_duplicate_member_across_files_raises(self, tmp_path: Path) -> None:
        _write_value_set_file(tmp_path / "a.json", "2026.08", "set_a", "1")
        _write_value_set_file(tmp_path / "b.json", "2026.08", "set_a", "1")
        with pytest.raises(ValueError, match="duplicate value-set member"):
            _load_from(tmp_path)

    def test_empty_directory_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="no value-set JSON files"):
            _load_from(tmp_path)
