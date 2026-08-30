"""Canonical serialization for the golden feature files.

Shared by ``tests/integration/test_features_as_of.py`` and ``scripts/regen_goldens.py`` so the
committed goldens and the test-side serialization can never drift apart. Rules:

- rows are keyed ``"<source>:<patient_id>"`` in one top-level object,
- dates/datetimes become ISO-8601 strings, ``Decimal`` becomes ``float``,
- output is ``sort_keys=True``, ``indent=2``, with a trailing newline — reviewable diffs.
"""

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any


def canonicalize_value(value: Any) -> Any:
    """JSON-safe scalar: Decimal -> float, date/datetime -> ISO string, rest unchanged."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):  # before date: datetime is a date subclass
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def canonicalize_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Key feature rows by ``source:patient_id`` with every value made JSON-safe."""
    keyed: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = f"{row['source']}:{row['patient_id']}"
        if key in keyed:
            raise ValueError(f"duplicate feature row for {key}")
        keyed[key] = {name: canonicalize_value(value) for name, value in row.items()}
    return keyed


def canonical_json(payload: dict[str, dict[str, Any]]) -> str:
    """The one true golden-file text form (sorted keys, indent=2, trailing newline)."""
    return json.dumps(payload, sort_keys=True, indent=2) + "\n"


def serialize_feature_rows(rows: list[dict[str, Any]]) -> str:
    """Feature rows -> canonical golden-file text in one step."""
    return canonical_json(canonicalize_rows(rows))
