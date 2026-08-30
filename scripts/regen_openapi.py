"""Regenerate the committed OpenAPI snapshot at ``docs/openapi.json``.

Run:  uv run python scripts/regen_openapi.py

The snapshot is asserted by ``tests/integration/test_openapi_snapshot.py``: any change to the
API surface must go through this script so the diff is committed and reviewable.
"""

import json
import tempfile
from pathlib import Path

from fhir_features.api.app import create_app
from fhir_features.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = REPO_ROOT / "docs" / "openapi.json"


def main() -> None:
    # app.openapi() never touches the DB (only the lifespan does), but pass a throwaway
    # path anyway so this script can never write a stray DuckDB file into the repo.
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(Settings(db_path=Path(tmp) / "openapi.duckdb"))
        spec = app.openapi()
    SNAPSHOT_PATH.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {SNAPSHOT_PATH}")


if __name__ == "__main__":
    main()
