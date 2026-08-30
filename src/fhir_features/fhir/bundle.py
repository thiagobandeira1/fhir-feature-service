"""Bundle envelope handling: validation, urn:uuid reference map, canonical hash.

The envelope is where untrusted-input enforcement lives. The one-bundle-one-patient invariant
is validated (not assumed) because the transactional per-patient replace depends on it.
Errors never echo resource content — codes and JSON pointers only.
"""

import hashlib
import json
from collections.abc import Mapping
from typing import Any

RefMap = Mapping[str, tuple[str, str]]
"""fullUrl (e.g. ``urn:uuid:<id>``) -> (resourceType, resource id)."""


class BundleValidationError(ValueError):
    """The payload is not an ingestible bundle. Carries an issue code, never content."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def canonical_bundle_hash(bundle: Mapping[str, Any]) -> str:
    """sha256 of the canonicalized JSON (sorted keys, no whitespace) — the idempotency key."""
    canonical = json.dumps(bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_bundle(payload: Any) -> list[dict[str, Any]]:
    """Validate the envelope; return the entry list. Raises :class:`BundleValidationError`.

    Rules: JSON object, ``resourceType == "Bundle"``, ``entry`` a list of objects each holding a
    ``resource`` object with a ``resourceType``; exactly one Patient resource.
    """
    if not isinstance(payload, dict):
        raise BundleValidationError("not_a_json_object", "payload is not a JSON object")
    if payload.get("resourceType") != "Bundle":
        raise BundleValidationError("not_a_bundle", "resourceType is not 'Bundle'")
    entries = payload.get("entry")
    if not isinstance(entries, list):
        raise BundleValidationError("missing_entries", "Bundle.entry is missing or not a list")
    patient_count = 0
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict) or not isinstance(entry.get("resource"), dict):
            raise BundleValidationError("malformed_entry", f"entry {i} has no resource object")
        resource_type = entry["resource"].get("resourceType")
        if not isinstance(resource_type, str) or not resource_type:
            raise BundleValidationError("missing_resource_type", f"entry {i} lacks resourceType")
        if resource_type == "Patient":
            patient_count += 1
    if patient_count != 1:
        raise BundleValidationError(
            "patient_count_invalid",
            f"bundle must contain exactly one Patient resource, found {patient_count}",
        )
    return entries


def build_reference_map(entries: list[dict[str, Any]]) -> dict[str, tuple[str, str]]:
    """Map every entry's fullUrl to (resourceType, id) for urn:uuid resolution."""
    refmap: dict[str, tuple[str, str]] = {}
    for entry in entries:
        resource = entry["resource"]
        full_url = entry.get("fullUrl")
        resource_id = resource.get("id")
        if isinstance(full_url, str) and isinstance(resource_id, str):
            refmap[full_url] = (resource["resourceType"], resource_id)
    return refmap


def resolve_reference(ref: str | None, refmap: RefMap) -> tuple[str, str] | None:
    """Resolve a FHIR reference string to (resourceType, id).

    Handles urn:uuid fullUrl references via the map and relative ``Type/id`` literals directly.
    Returns None when unresolvable (caller records a dangling-reference warning).
    """
    if not ref:
        return None
    if ref in refmap:
        return refmap[ref]
    if "/" in ref and not ref.startswith(("http:", "https:", "urn:")):
        resource_type, _, resource_id = ref.partition("/")
        if resource_type and resource_id:
            return (resource_type, resource_id)
    return None
