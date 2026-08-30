"""API integration suite: every endpoint, happy and error paths, over a tmp DuckDB.

Errors must be RFC 9457 ``application/problem+json`` and must never echo resource content —
every error body is checked against committed persona-name sentinels. The ``with TestClient``
blocks are load-bearing: they trigger the lifespan (migrations + value-set sync).
"""

import gzip
import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any, NamedTuple

import httpx
import pytest
from fastapi.testclient import TestClient

import fhir_features
from fhir_features.api.app import create_app
from fhir_features.config import Settings
from fhir_features.features.registry import FEATURE_VERSION, feature_names

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "synthetic" / "samples"

#: Substrings of committed persona names; they must never appear in any response body.
NAME_SENTINELS = ("Tony646", "Mosciski958")

PINNED_AS_OF = "2024-01-01"

RECORD_SECTION_NAMES = (
    "conditions",
    "observations",
    "procedures",
    "medications",
    "encounters",
    "immunizations",
    "claim_diagnoses",
)


def load_sample_bundle(name_prefix: str) -> dict[str, Any]:
    """Load a committed gzipped Synthea bundle by filename prefix."""
    matches = sorted(SAMPLES_DIR.glob(f"{name_prefix}*.json.gz"))
    assert len(matches) == 1, f"expected exactly one sample for {name_prefix!r}, got {matches}"
    with gzip.open(matches[0], "rt", encoding="utf-8") as fh:
        data: dict[str, Any] = json.load(fh)
    return data


def assert_request_id(response: httpx.Response) -> None:
    header = response.headers.get("x-request-id")
    assert header is not None, "x-request-id header missing"
    uuid.UUID(header)  # must be a well-formed UUID


def assert_no_patient_names(response: httpx.Response) -> None:
    for sentinel in NAME_SENTINELS:
        assert sentinel not in response.text, f"patient name sentinel {sentinel!r} leaked"


def assert_problem(response: httpx.Response, status: int, code: str) -> dict[str, Any]:
    """Assert an RFC 9457 problem+json error with the given status and issue code."""
    assert response.status_code == status
    assert response.headers["content-type"].startswith("application/problem+json")
    body: dict[str, Any] = response.json()
    assert body["status"] == status
    assert body["code"] == code
    assert body["title"]
    assert_no_patient_names(response)
    assert_request_id(response)
    return body


@pytest.fixture()
def client(tmp_path: Path) -> Iterator[TestClient]:
    """A fresh app over an empty tmp DuckDB (lifespan runs migrations + value sets)."""
    app = create_app(Settings(db_path=tmp_path / "api.duckdb"))
    with TestClient(app) as test_client:
        yield test_client


class SeededApi(NamedTuple):
    client: TestClient
    chet_id: str
    tony_id: str


@pytest.fixture(scope="module")
def seeded(tmp_path_factory: pytest.TempPathFactory) -> Iterator[SeededApi]:
    """One app per module with the Chet188 and Tony646 personas ingested (read-only tests)."""
    db_path = tmp_path_factory.mktemp("api-seeded") / "seeded.duckdb"
    app = create_app(Settings(db_path=db_path))
    with TestClient(app) as test_client:
        ids: dict[str, str] = {}
        for prefix in ("Chet188", "Tony646"):
            response = test_client.post("/v1/ingest/bundle", json=load_sample_bundle(prefix))
            assert response.status_code == 200, response.text
            ids[prefix] = response.json()["patient_id"]
        yield SeededApi(test_client, ids["Chet188"], ids["Tony646"])


# --- /healthz ------------------------------------------------------------------------------


def test_healthz_reports_versions(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service_version"] == fhir_features.__version__
    assert body["schema_version"] >= 3
    assert body["feature_version"] == FEATURE_VERSION
    assert_request_id(response)


def test_request_ids_are_unique_per_request(client: TestClient) -> None:
    first = client.get("/healthz")
    second = client.get("/healthz")
    assert_request_id(first)
    assert_request_id(second)
    assert first.headers["x-request-id"] != second.headers["x-request-id"]


# --- POST /v1/ingest/bundle ----------------------------------------------------------------


def test_ingest_created_then_unchanged(client: TestClient) -> None:
    bundle = load_sample_bundle("Chet188")
    first = client.post("/v1/ingest/bundle", json=bundle)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["action"] == "created"
    assert body["source"] == "synthea"
    assert body["patient_id"]
    assert len(body["bundle_hash"]) == 64
    counts = body["resource_counts"]
    assert counts["patients"] == 1
    assert counts["encounters"] > 0
    assert counts["conditions"] > 0
    assert counts["observations"] > 0
    assert isinstance(body["warnings"], list)
    assert "DiagnosticReport" in body["skipped_resource_types"]
    assert_request_id(first)

    second = client.post("/v1/ingest/bundle", json=bundle)
    assert second.status_code == 200, second.text
    repeat = second.json()
    assert repeat["action"] == "unchanged"
    assert repeat["bundle_hash"] == body["bundle_hash"]
    assert repeat["patient_id"] == body["patient_id"]
    assert repeat["resource_counts"] == {}


def test_ingest_malformed_json_body(client: TestClient) -> None:
    response = client.post(
        "/v1/ingest/bundle",
        content=b'{"resourceType": "Bundle", not json',
        headers={"content-type": "application/json"},
    )
    assert_problem(response, 422, "invalid_json")


def test_ingest_bundle_with_two_patients(client: TestClient) -> None:
    bundle: dict[str, Any] = {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {"resource": {"resourceType": "Patient", "id": "p-one", "gender": "male"}},
            {"resource": {"resourceType": "Patient", "id": "p-two", "gender": "female"}},
        ],
    }
    response = client.post("/v1/ingest/bundle", json=bundle)
    assert_problem(response, 422, "patient_count_invalid")


def test_ingest_oversized_body_is_413(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FF_MAX_BUNDLE_BYTES", "16")
    response = client.post(
        "/v1/ingest/bundle",
        content=b'{"resourceType": "Bundle", "entry": []}',
        headers={"content-type": "application/json"},
    )
    assert_problem(response, 413, "bundle_too_large")


# --- GET /v1/patients ----------------------------------------------------------------------


def test_patients_roster_pagination_and_ordering(seeded: SeededApi) -> None:
    full = seeded.client.get("/v1/patients")
    assert full.status_code == 200
    body = full.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2
    keys = [(item["source"], item["patient_id"]) for item in body["items"]]
    assert keys == sorted(keys), "roster must be ordered by (source, patient_id)"
    assert {item["patient_id"] for item in body["items"]} == {seeded.chet_id, seeded.tony_id}
    for item in body["items"]:
        assert item["source"] == "synthea"
        assert item["deceased"] is False

    page_one = seeded.client.get("/v1/patients", params={"limit": 1, "offset": 0}).json()
    page_two = seeded.client.get("/v1/patients", params={"limit": 1, "offset": 1}).json()
    assert page_one["total"] == 2
    assert page_two["total"] == 2
    assert len(page_one["items"]) == 1
    assert len(page_two["items"]) == 1
    paged_ids = [page_one["items"][0]["patient_id"], page_two["items"][0]["patient_id"]]
    assert paged_ids == [item["patient_id"] for item in body["items"]]


# --- GET /v1/patients/{id}/record ----------------------------------------------------------


def test_record_full(seeded: SeededApi) -> None:
    response = seeded.client.get(f"/v1/patients/{seeded.chet_id}/record")
    assert response.status_code == 200
    body = response.json()
    assert body["patient"]["patient_id"] == seeded.chet_id
    assert body["patient"]["source"] == "synthea"
    assert "ingested_at" not in body["patient"]
    assert "name" not in body["patient"]  # never parsed, can never be served
    assert set(body["counts"]) == set(RECORD_SECTION_NAMES)
    for section in RECORD_SECTION_NAMES:
        assert body["counts"][section] == len(body[section])
    assert body["counts"]["observations"] > 0
    assert body["counts"]["conditions"] > 0
    dates = [row["effective_date"] for row in body["observations"] if row["effective_date"]]
    assert dates == sorted(dates), "observations must be ordered by event date ascending"
    assert_request_id(response)


def test_record_sections_filter(seeded: SeededApi) -> None:
    response = seeded.client.get(
        f"/v1/patients/{seeded.chet_id}/record",
        params={"sections": "conditions,observations"},
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body["counts"]) == {"conditions", "observations"}
    assert len(body["conditions"]) == body["counts"]["conditions"] > 0
    assert len(body["observations"]) == body["counts"]["observations"] > 0
    for section in set(RECORD_SECTION_NAMES) - {"conditions", "observations"}:
        assert body[section] == []


def test_record_date_window_filters(seeded: SeededApi) -> None:
    base = f"/v1/patients/{seeded.chet_id}/record"
    full = seeded.client.get(base, params={"sections": "observations"}).json()
    windowed = seeded.client.get(
        base,
        params={"sections": "observations", "from": "2020-01-01", "to": "2021-12-31"},
    ).json()
    assert 0 < windowed["counts"]["observations"] < full["counts"]["observations"]
    for row in windowed["observations"]:
        assert row["effective_date"] is not None
        assert "2020-01-01" <= row["effective_date"] <= "2021-12-31"


def test_record_observation_codes_filter(seeded: SeededApi) -> None:
    base = f"/v1/patients/{seeded.chet_id}/record"
    full = seeded.client.get(base, params={"sections": "observations"}).json()
    filtered = seeded.client.get(
        base,
        params={"sections": "observations", "observation_codes": "8302-2"},
    ).json()
    assert 0 < filtered["counts"]["observations"] < full["counts"]["observations"]
    assert {row["code"] for row in filtered["observations"]} == {"8302-2"}


def test_record_unknown_section_is_422(seeded: SeededApi) -> None:
    response = seeded.client.get(
        f"/v1/patients/{seeded.chet_id}/record", params={"sections": "conditions,bogus"}
    )
    body = assert_problem(response, 422, "unknown_section")
    assert "bogus" in body["detail"]


def test_record_unknown_patient_is_404(seeded: SeededApi) -> None:
    response = seeded.client.get("/v1/patients/no-such-patient/record")
    assert_problem(response, 404, "not_found")


# --- GET /v1/patients/{id}/features --------------------------------------------------------


def test_patient_features_pinned_as_of(seeded: SeededApi) -> None:
    response = seeded.client.get(
        f"/v1/patients/{seeded.tony_id}/features", params={"as_of": PINNED_AS_OF}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["feature_version"] == FEATURE_VERSION == "v1"
    assert isinstance(body["valuesets_version"], str)
    assert body["valuesets_version"]
    features = body["features"]
    assert set(features) == set(feature_names())
    assert features["as_of"] == PINNED_AS_OF
    assert features["patient_id"] == seeded.tony_id
    assert features["source"] == "synthea"
    assert_no_patient_names(response)


def test_patient_features_unknown_patient_is_404(seeded: SeededApi) -> None:
    response = seeded.client.get("/v1/patients/no-such-patient/features")
    assert_problem(response, 404, "not_found")


# --- GET /v1/features ----------------------------------------------------------------------


def test_features_page_pinned_as_of(seeded: SeededApi) -> None:
    response = seeded.client.get("/v1/features", params={"as_of": PINNED_AS_OF})
    assert response.status_code == 200
    body = response.json()
    assert body["as_of"] == PINNED_AS_OF
    assert body["feature_version"] == FEATURE_VERSION
    assert body["valuesets_version"]
    assert body["total"] == 2
    assert len(body["items"]) == 2
    keys = [(item["source"], item["patient_id"]) for item in body["items"]]
    assert keys == sorted(keys), "feature rows must be ordered by (source, patient_id)"
    for item in body["items"]:
        assert set(item) == set(feature_names())
        assert item["as_of"] == PINNED_AS_OF

    page = seeded.client.get(
        "/v1/features", params={"as_of": PINNED_AS_OF, "limit": 1, "offset": 1}
    ).json()
    assert page["total"] == 2
    assert len(page["items"]) == 1
    assert page["items"][0]["patient_id"] == body["items"][1]["patient_id"]


# --- GET /v1/features/schema ---------------------------------------------------------------


def test_features_schema_matches_registry(seeded: SeededApi) -> None:
    response = seeded.client.get("/v1/features/schema")
    assert response.status_code == 200
    body = response.json()
    assert body["feature_version"] == FEATURE_VERSION
    assert body["valuesets_version"]
    assert body["as_of_semantics"]
    names = [field["name"] for field in body["features"]]
    assert len(names) == len(feature_names())
    assert names == feature_names()
    for field in body["features"]:
        assert set(field) == {"name", "type", "nullable", "description", "value_set_id", "added_in"}


# --- GET /v1/panel/summary -----------------------------------------------------------------


def test_panel_summary_shape(seeded: SeededApi) -> None:
    response = seeded.client.get("/v1/panel/summary", params={"as_of": PINNED_AS_OF})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "as_of",
        "patient_count",
        "avg_age",
        "pct_female",
        "prevalence",
        "tobacco_unscreened_count",
        "encounters_365d_total",
        "ed_visits_365d_total",
        "inpatient_admits_365d_total",
    }
    assert body["as_of"] == PINNED_AS_OF
    assert body["patient_count"] == 2  # both committed personas are alive at the pinned date
    assert body["pct_female"] == 0.0  # both personas are male
    assert isinstance(body["avg_age"], float)
    assert set(body["prevalence"]) == {"diabetes", "hypertension", "ascvd", "ckd", "chf", "copd"}
    for value in body["prevalence"].values():
        assert value is None or 0.0 <= value <= 1.0
    for key in (
        "tobacco_unscreened_count",
        "encounters_365d_total",
        "ed_visits_365d_total",
        "inpatient_admits_365d_total",
    ):
        assert isinstance(body[key], int)
        assert body[key] >= 0
    assert_request_id(response)
