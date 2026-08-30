"""Unit tests for bundle envelope handling: canonical hash, validation, reference resolution."""

import json
from pathlib import Path
from typing import Any

import pytest

from fhir_features.fhir.bundle import (
    BundleValidationError,
    build_reference_map,
    canonical_bundle_hash,
    resolve_reference,
    validate_bundle,
)

MALFORMED_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "malformed"


def load_malformed(name: str) -> Any:
    """Load a handwritten malformed-payload fixture by filename."""
    return json.loads((MALFORMED_DIR / name).read_text(encoding="utf-8"))


def minimal_bundle() -> dict[str, Any]:
    """The smallest valid bundle: one Patient entry with a urn:uuid fullUrl."""
    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {
                "fullUrl": "urn:uuid:pat-1",
                "resource": {"resourceType": "Patient", "id": "pat-1"},
            },
            {
                "fullUrl": "urn:uuid:enc-1",
                "resource": {"resourceType": "Encounter", "id": "enc-1"},
            },
        ],
    }


class TestCanonicalBundleHash:
    def test_stable_under_key_reordering(self) -> None:
        """Same content in a different insertion order must yield the identical hash."""
        forward = {
            "resourceType": "Bundle",
            "type": "transaction",
            "entry": [{"resource": {"resourceType": "Patient", "id": "pat-1"}}],
        }
        reordered = {
            "entry": [{"resource": {"id": "pat-1", "resourceType": "Patient"}}],
            "type": "transaction",
            "resourceType": "Bundle",
        }
        assert canonical_bundle_hash(forward) == canonical_bundle_hash(reordered)

    def test_changes_when_any_value_changes(self) -> None:
        original = minimal_bundle()
        mutated = minimal_bundle()
        mutated["entry"][0]["resource"]["id"] = "pat-2"
        assert canonical_bundle_hash(original) != canonical_bundle_hash(mutated)

    def test_is_hex_sha256(self) -> None:
        digest = canonical_bundle_hash(minimal_bundle())
        assert len(digest) == 64
        assert set(digest) <= set("0123456789abcdef")


class TestValidateBundle:
    def test_happy_path_returns_entries(self) -> None:
        bundle = minimal_bundle()
        entries = validate_bundle(bundle)
        assert entries is bundle["entry"]
        assert len(entries) == 2

    @pytest.mark.parametrize(
        ("fixture", "expected_code"),
        [
            ("not_a_bundle.json", "not_a_bundle"),
            ("zero_patients.json", "patient_count_invalid"),
            ("two_patients.json", "patient_count_invalid"),
            ("malformed_entry.json", "malformed_entry"),
        ],
    )
    def test_malformed_fixture_raises_with_code(self, fixture: str, expected_code: str) -> None:
        payload = load_malformed(fixture)
        with pytest.raises(BundleValidationError) as excinfo:
            validate_bundle(payload)
        assert excinfo.value.code == expected_code

    def test_non_object_payload(self) -> None:
        with pytest.raises(BundleValidationError) as excinfo:
            validate_bundle(["not", "an", "object"])
        assert excinfo.value.code == "not_a_json_object"

    def test_missing_entry_list(self) -> None:
        with pytest.raises(BundleValidationError) as excinfo:
            validate_bundle({"resourceType": "Bundle"})
        assert excinfo.value.code == "missing_entries"


class TestBuildReferenceMap:
    def test_maps_urn_uuid_full_urls(self) -> None:
        refmap = build_reference_map(validate_bundle(minimal_bundle()))
        assert refmap["urn:uuid:pat-1"] == ("Patient", "pat-1")
        assert refmap["urn:uuid:enc-1"] == ("Encounter", "enc-1")

    def test_entry_without_full_url_or_id_is_skipped(self) -> None:
        entries: list[dict[str, Any]] = [
            {"resource": {"resourceType": "Patient", "id": "pat-1"}},  # no fullUrl
            {"fullUrl": "urn:uuid:enc-1", "resource": {"resourceType": "Encounter"}},  # no id
        ]
        assert build_reference_map(entries) == {}


class TestResolveReference:
    def test_urn_uuid_hit(self) -> None:
        refmap = {"urn:uuid:pat-1": ("Patient", "pat-1")}
        assert resolve_reference("urn:uuid:pat-1", refmap) == ("Patient", "pat-1")

    def test_relative_type_id_literal(self) -> None:
        assert resolve_reference("Patient/pat-9", {}) == ("Patient", "pat-9")

    def test_dangling_urn_uuid_returns_none(self) -> None:
        assert resolve_reference("urn:uuid:missing", {}) is None

    def test_absolute_http_url_returns_none(self) -> None:
        assert resolve_reference("http://example.org/fhir/Patient/pat-1", {}) is None
        assert resolve_reference("https://example.org/fhir/Patient/pat-1", {}) is None

    def test_missing_reference_returns_none(self) -> None:
        assert resolve_reference(None, {}) is None
        assert resolve_reference("", {}) is None
