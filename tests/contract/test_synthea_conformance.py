"""The executable adapter contract, run against the committed persona fixtures.

The future MIMIC adapter (separate, local-only repo) imports this exact suite from the
installed package and must pass it identically.
"""

from pathlib import Path

import pytest

from fhir_features.adapters.base import SourceAdapter
from fhir_features.adapters.mimic import MimicAdapter, MimicConfigError
from fhir_features.adapters.synthea import SyntheaBundleAdapter
from fhir_features.testing import assert_conforms

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "synthetic" / "samples"


def test_synthea_adapter_conforms() -> None:
    assert_conforms(SyntheaBundleAdapter(SAMPLES_DIR))


def test_synthea_adapter_satisfies_protocol() -> None:
    adapter: SourceAdapter = SyntheaBundleAdapter(SAMPLES_DIR)
    assert adapter.source == "synthea"


def test_mimic_stub_satisfies_protocol_but_is_unimplemented(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    outside = tmp_path_factory.mktemp("mimic-outside-repo")
    monkeypatch.setenv("MIMIC_CSV_DIR", str(outside))
    adapter: SourceAdapter = MimicAdapter()
    assert adapter.source == "mimic"
    with pytest.raises(NotImplementedError):
        next(iter(adapter.iter_patient_records()))


def test_mimic_stub_rejects_in_repo_data_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIMIC_CSV_DIR", str(SAMPLES_DIR))
    with pytest.raises(MimicConfigError, match="outside the repository"):
        MimicAdapter()


def test_mimic_stub_requires_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MIMIC_CSV_DIR", raising=False)
    monkeypatch.delenv("MIMIC_DB_URL", raising=False)
    with pytest.raises(MimicConfigError, match="MIMIC_CSV_DIR or MIMIC_DB_URL"):
        MimicAdapter()
