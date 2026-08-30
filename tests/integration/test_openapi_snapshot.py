"""The committed OpenAPI snapshot (docs/openapi.json) cannot drift from the live app."""

import json
from pathlib import Path

from fhir_features.api.app import create_app
from fhir_features.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_PATH = REPO_ROOT / "docs" / "openapi.json"


def test_openapi_matches_committed_snapshot(tmp_path: Path) -> None:
    # app.openapi() is pure schema generation — no lifespan, so no DB is ever opened.
    app = create_app(Settings(db_path=tmp_path / "unused.duckdb"))
    # Round-trip through JSON so the comparison sees exactly what the snapshot file stores.
    live = json.loads(json.dumps(app.openapi(), sort_keys=True))
    committed = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    assert live == committed, (
        "OpenAPI schema drifted from docs/openapi.json — regenerate it with "
        "'uv run python scripts/regen_openapi.py' and commit the reviewed diff"
    )
