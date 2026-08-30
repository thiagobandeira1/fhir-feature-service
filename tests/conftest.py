"""Shared fixtures: tmp DuckDB (migrated), sample-bundle loaders, log capture."""

import gzip
import json
from pathlib import Path
from typing import Any

import pytest

from fhir_features.store.db import Database
from fhir_features.store.migrate import migrate

SAMPLES_DIR = Path(__file__).resolve().parents[1] / "synthetic" / "samples"


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.duckdb")
    migrate(database)
    yield database  # type: ignore[misc]
    database.close()


def load_sample_bundle(name_prefix: str) -> dict[str, Any]:
    """Load a committed gzipped Synthea bundle by filename prefix."""
    matches = sorted(SAMPLES_DIR.glob(f"{name_prefix}*.json.gz"))
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one sample for {name_prefix!r}, got {matches}")
    with gzip.open(matches[0], "rt", encoding="utf-8") as fh:
        data: dict[str, Any] = json.load(fh)
    return data


@pytest.fixture(scope="session")
def diabetic_bundle() -> dict[str, Any]:
    return load_sample_bundle("Tony646")


@pytest.fixture(scope="session")
def deceased_bundle() -> dict[str, Any]:
    return load_sample_bundle("Kayce253")
