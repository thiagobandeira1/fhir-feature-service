"""Committed value-set JSON: loading, merging, and validation.

The JSON files under ``value_sets/`` are DEMO-GRADE curated sets built from public code systems
(SNOMED CT, LOINC, RxNorm, CVX) cross-checked against the codes that actually appear in the
generated Synthea data. They are NOT NCQA HEDIS value sets and contain no NCQA/VSAC licensed
content — real measure programs would swap in licensed sets (see SPEC section 10).

Loading is strict on purpose: these files are committed reference data (not untrusted input),
so a duplicate member or a version mismatch across files is a packaging bug and raises.
"""

import json
from importlib import resources
from importlib.resources.abc import Traversable
from typing import Literal

from pydantic import BaseModel, ConfigDict

CodeSystem = Literal["SNOMED", "LOINC", "RXNORM", "CVX"]
"""Normalized short names (see ``canonical.codes``) the v1 value sets are allowed to use."""


class ValueSetMember(BaseModel):
    """One (value set, code) membership row, as loaded into ``value_set_members``."""

    model_config = ConfigDict(frozen=True)

    value_set_id: str
    code_system: CodeSystem
    code: str
    display: str


class ValueSetBundle(BaseModel):
    """Every value-set member across all committed JSON files, under one CalVer version."""

    model_config = ConfigDict(frozen=True)

    version: str
    members: list[ValueSetMember]


def _load_from(root: Traversable) -> ValueSetBundle:
    """Merge every ``*.json`` under ``root``; raise ``ValueError`` on any inconsistency."""
    version: str | None = None
    members: list[ValueSetMember] = []
    seen: set[tuple[str, str, str]] = set()
    for entry in sorted(root.iterdir(), key=lambda t: t.name):
        if not entry.name.endswith(".json"):
            continue
        payload = json.loads(entry.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"{entry.name}: top level is not a JSON object")
        file_version = payload.get("valuesets_version")
        if not isinstance(file_version, str) or not file_version:
            raise ValueError(f"{entry.name}: missing valuesets_version")
        if version is None:
            version = file_version
        elif file_version != version:
            raise ValueError(
                f"{entry.name}: valuesets_version {file_version!r} does not match {version!r}"
            )
        value_sets = payload.get("value_sets")
        if not isinstance(value_sets, dict):
            raise ValueError(f"{entry.name}: missing value_sets object")
        for value_set_id, spec in value_sets.items():
            if not isinstance(spec, dict) or not isinstance(spec.get("codes"), list):
                raise ValueError(f"{entry.name}: value set {value_set_id!r} lacks a codes list")
            for item in spec["codes"]:
                if not isinstance(item, dict):
                    raise ValueError(f"{entry.name}: {value_set_id!r} has a non-object code entry")
                member = ValueSetMember.model_validate(
                    {
                        "value_set_id": value_set_id,
                        "code_system": spec.get("code_system"),
                        "code": item.get("code"),
                        "display": item.get("display"),
                    }
                )
                key = (member.value_set_id, member.code_system, member.code)
                if key in seen:
                    raise ValueError(f"duplicate value-set member: {key}")
                seen.add(key)
                members.append(member)
    if version is None:
        raise ValueError("no value-set JSON files found")
    return ValueSetBundle(version=version, members=members)


def load_value_sets() -> ValueSetBundle:
    """Load and merge ALL ``*.json`` files shipped in the ``value_sets`` package directory."""
    return _load_from(resources.files("fhir_features.features") / "value_sets")
