"""Regenerate the committed golden feature files (tests/golden/features_<as_of>.json).

Goldens are the trust core (SPEC section 9.4): they only change through THIS script so every
change lands as a reviewable diff. It ingests the five committed personas from
``synthetic/samples`` into a throwaway DuckDB (migrate + value-set sync, mirroring the CLI's
``_open_db`` with an explicit temp path), computes features at the two pinned ``as_of`` dates,
and writes them with the same canonical serializer the golden test uses.

Usage:  uv run python scripts/regen_goldens.py
"""

import sys
import tempfile
from datetime import date
from pathlib import Path

import fhir_features
from fhir_features.adapters.synthea import SyntheaBundleAdapter
from fhir_features.features.queries import compute_features
from fhir_features.features.value_sets import load_value_sets
from fhir_features.store.db import Database
from fhir_features.store.loader import load_patient
from fhir_features.store.migrate import migrate
from fhir_features.store.reference import sync_value_sets

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLES_DIR = REPO_ROOT / "synthetic" / "samples"
GOLDEN_DIR = REPO_ROOT / "tests" / "golden"

# scripts/ is not a package; the serializer lives beside the tests that consume the goldens.
sys.path.insert(0, str(REPO_ROOT / "tests"))
from golden_util import serialize_feature_rows  # noqa: E402

#: The two pinned dates of SPEC section 9.4 — one mid-history, one recent.
PINNED_AS_OF_DATES = (date(2023, 6, 30), date(2025, 12, 31))


def _open_temp_db(db_path: Path) -> Database:
    """Mirror ``fhir_features.cli._open_db`` (migrate + value-set sync) at an explicit path."""
    db = Database(db_path)
    migrate(db)
    sync_value_sets(db, load_value_sets())
    return db


def _ingest_samples(db: Database) -> int:
    adapter = SyntheaBundleAdapter(SAMPLES_DIR)
    count = 0
    for record_set in adapter.iter_patient_records():
        load_patient(
            db,
            record_set,
            bundle_hash=None,
            raw_payload=None,
            service_version=fhir_features.__version__,
        )
        count += 1
    return count


def main() -> int:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    with (
        tempfile.TemporaryDirectory(prefix="regen-goldens-") as tmp,
        _open_temp_db(Path(tmp) / "goldens.duckdb") as db,
    ):
        patient_count = _ingest_samples(db)
        print(f"ingested {patient_count} persona bundle(s) from {SAMPLES_DIR}")
        for as_of in PINNED_AS_OF_DATES:
            rows = compute_features(db, as_of)
            if len(rows) != patient_count:
                raise AssertionError(
                    f"expected {patient_count} feature rows at {as_of}, got {len(rows)}"
                )
            target = GOLDEN_DIR / f"features_{as_of.isoformat()}.json"
            target.write_text(serialize_feature_rows(rows), encoding="utf-8", newline="\n")
            print(f"wrote {target.relative_to(REPO_ROOT)} ({len(rows)} rows)")
    print("review the diff before committing - goldens are the behavioural contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
