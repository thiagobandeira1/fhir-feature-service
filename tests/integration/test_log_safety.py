"""Log-safety enforcement for the deny-by-default logging ADR (ADR-0008).

The allowlist in :mod:`fhir_features.logging_setup` is only as good as its enforcement test.
These tests capture everything written to the real stdout/stderr file descriptors (structlog's
default ``PrintLogger`` sink) while (1) ingesting every committed persona bundle directly through
the adapter + loader and (2) exercising a full HTTP pass over the API, then assert that no
patient name, birth date, or file path reached the sink — and that log lines DID appear, every
one a JSON object carrying only allowlisted keys (so the test can never pass vacuously).
"""

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import fhir_features
from fhir_features.adapters.synthea import load_bundle_file, record_set_from_bundle
from fhir_features.api.app import create_app
from fhir_features.config import Settings
from fhir_features.fhir.bundle import canonical_bundle_hash
from fhir_features.logging_setup import ALLOWED_KEYS, configure_logging
from fhir_features.store.db import Database
from fhir_features.store.loader import load_patient

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "synthetic" / "samples"

#: Every name part of every committed persona. None may ever reach a log sink.
SENTINEL_NAMES: tuple[str, ...] = (
    "Tony646",
    "Mosciski958",
    "Sheryl275",
    "Angelo118",
    "Stiedemann542",
    "Chet188",
    "Hammes673",
    "Meredith572",
    "McClure239",
    "Kayce253",
    "Rowe323",
)


def _patient_dates(bundle: Mapping[str, Any]) -> list[str]:
    """birthDate (and the date part of deceasedDateTime) of every Patient in the bundle."""
    dates: list[str] = []
    for entry in bundle.get("entry", []):
        resource = entry.get("resource") or {}
        if resource.get("resourceType") != "Patient":
            continue
        birth = resource.get("birthDate")
        if isinstance(birth, str):
            dates.append(birth)
        deceased = resource.get("deceasedDateTime")
        if isinstance(deceased, str):
            dates.append(deceased[:10])
    return dates


def _events_from_stdout(out: str) -> list[dict[str, Any]]:
    """Parse captured stdout: every line at the sink must be JSON with only allowlisted keys."""
    events: list[dict[str, Any]] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError as exc:
            raise AssertionError(f"non-JSON output reached the log sink: {line!r}") from exc
        assert isinstance(event, dict), f"non-object log line reached the sink: {line!r}"
        unexpected = set(event) - ALLOWED_KEYS
        assert not unexpected, f"non-allowlisted keys reached the log sink: {sorted(unexpected)}"
        events.append(event)
    assert events, "no structured log lines were captured; the safety test would be vacuous"
    return events


def _assert_no_sentinels(text: str, sensitive_dates: list[str]) -> None:
    lower = text.lower()
    for name in SENTINEL_NAMES:
        assert name.lower() not in lower, f"patient name {name!r} leaked into log output"
    assert sensitive_dates, "no patient dates extracted; date-leak assertions would be vacuous"
    for value in sensitive_dates:
        assert value not in text, f"patient date {value!r} leaked into log output"
    assert "synthetic" not in lower, "sample directory name leaked into log output"
    assert ".json.gz" not in lower, "bundle filename leaked into log output"
    # Covers raw "C:\Users" and its JSON-escaped "C:\\Users" form alike.
    assert "\\users" not in lower, "absolute file path leaked into log output"


def test_direct_ingest_log_output_is_clean(db: Database, capfd: pytest.CaptureFixture[str]) -> None:
    """Ingest every committed persona via adapter + loader; nothing sensitive reaches the sink."""
    configure_logging()
    capfd.readouterr()  # drain fixture-setup output; capture only what the ingest emits

    sample_files = sorted(SAMPLES_DIR.glob("*.json.gz"))
    assert len(sample_files) == 5, "expected the five committed persona bundles"

    sensitive_dates: list[str] = []
    for path in sample_files:
        bundle = load_bundle_file(path)
        dates = _patient_dates(bundle)
        assert dates, f"no Patient dates extracted from {path.name}"
        sensitive_dates.extend(dates)
        result = load_patient(
            db,
            record_set_from_bundle(bundle),
            bundle_hash=canonical_bundle_hash(bundle),
            raw_payload=json.dumps(bundle, separators=(",", ":")),
            service_version=fhir_features.__version__,
        )
        assert result.action == "created"

    captured = capfd.readouterr()
    events = _events_from_stdout(captured.out)

    loaded = [e for e in events if e.get("event") == "patient_loaded"]
    assert len(loaded) == 5, "one patient_loaded event per persona proves capture works"
    for event in loaded:
        assert event["action"] == "created"
        assert re.fullmatch(r"[0-9a-f]{64}", event["bundle_hash"])
        assert event["row_counts"]["patients"] == 1

    _assert_no_sentinels(captured.out + captured.err, sensitive_dates)


def test_api_round_trip_log_output_is_clean(
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
    diabetic_bundle: dict[str, Any],
) -> None:
    """Full TestClient pass (lifespan, ingest, reads, 404, 422); the sink stays sentinel-free."""
    app = create_app(Settings(db_path=tmp_path / "api.duckdb"))
    capfd.readouterr()  # drain; lifespan output inside the with-block is part of the capture

    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200

        ingest = client.post(
            "/v1/ingest/bundle",
            content=json.dumps(diabetic_bundle).encode("utf-8"),
            headers={"content-type": "application/json"},
        )
        assert ingest.status_code == 200
        patient_id = ingest.json()["patient_id"]

        assert client.get(f"/v1/patients/{patient_id}/record").status_code == 200
        assert client.get(f"/v1/patients/{patient_id}/features").status_code == 200
        assert client.get("/v1/patients/no-such-patient/record").status_code == 404
        invalid = client.post(
            "/v1/ingest/bundle",
            content=b'{"resourceType": not-json',
            headers={"content-type": "application/json"},
        )
        assert invalid.status_code == 422

    captured = capfd.readouterr()
    events = _events_from_stdout(captured.out)

    event_names = [e.get("event") for e in events]
    assert "service_started" in event_names, "lifespan startup log proves capture covers the app"
    assert "patient_loaded" in event_names

    requests = [e for e in events if e.get("event") == "request"]
    assert len(requests) == 6, "one access-log event per HTTP call"
    assert {e["status_code"] for e in requests} == {200, 404, 422}
    for event in requests:
        assert event["method"] in {"GET", "POST"}
        assert str(event["path"]).startswith(("/healthz", "/v1/"))

    _assert_no_sentinels(captured.out + captured.err, _patient_dates(diabetic_bundle))


def test_allowlist_never_contains_identity_keys() -> None:
    """Pin the allowlist's teeth: identity/content keys stay off, operational keys stay on."""
    forbidden = {
        "patient_id",
        "name",
        "birth_date",
        "birthDate",
        "death_date",
        "address",
        "city",
        "state",
        "postal_code",
        "raw_payload",
        "body",
        "detail",
        "file",
        "filename",
        "bundle_path",
    }
    assert forbidden.isdisjoint(ALLOWED_KEYS)
    assert {"event", "action", "bundle_hash", "status_code"} <= ALLOWED_KEYS
