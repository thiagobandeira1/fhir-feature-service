"""Schema-contract drift guards (SPEC section 9.5).

Three legs, so registry, SQL, and value sets cannot drift apart:

1. The columns produced by ``patient_features_v1.sql`` match the registry — names AND order.
2. Every ``value_set_id`` a :class:`FeatureSpec` declares exists among the loaded value sets.
3. Every value-set id literal referenced inside the SQL text is a loaded value set.
"""

import re
from datetime import date
from importlib import resources

from fhir_features.features.registry import FEATURES, feature_names
from fhir_features.features.value_sets import load_value_sets
from fhir_features.store.db import Database

_SQL = (resources.files("fhir_features.features") / "sql" / "patient_features_v1.sql").read_text(
    encoding="utf-8"
)


def _loaded_value_set_ids() -> set[str]:
    return {member.value_set_id for member in load_value_sets().members}


def test_sql_columns_match_registry_names_and_order(db: Database) -> None:
    """The registry is the contract for /v1/features/schema; the SQL must produce exactly it.

    An empty (freshly migrated) DB is enough: cursor.description exposes the projected
    columns even with zero rows.
    """
    cursor = db.conn.execute(_SQL, [date(2025, 1, 1)])
    sql_columns = [column[0] for column in cursor.description]
    assert sql_columns == feature_names(), (
        "patient_features_v1.sql columns diverged from features.registry.FEATURES "
        "(names and order must match exactly)"
    )


def test_registry_value_set_ids_exist_in_loaded_value_sets() -> None:
    loaded = _loaded_value_set_ids()
    referenced = {spec.value_set_id for spec in FEATURES if spec.value_set_id is not None}
    assert referenced, "registry declares no value_set_ids — registry gutted?"
    missing = referenced - loaded
    assert not missing, f"registry references value sets not in committed JSON: {sorted(missing)}"


def test_sql_value_set_literals_are_loaded() -> None:
    """Every value_set_id string literal in the SQL must be a committed, loaded value set."""
    referenced: set[str] = set(re.findall(r"value_set_id\s*=\s*'([^']+)'", _SQL))
    for in_list in re.findall(r"value_set_id\s+IN\s*\(([^)]*)\)", _SQL, flags=re.DOTALL):
        referenced.update(re.findall(r"'([^']+)'", in_list))
    assert referenced, (
        "no value_set_id literals found in patient_features_v1.sql — "
        "either the SQL stopped using value sets or this test's regexes are stale"
    )
    loaded = _loaded_value_set_ids()
    unknown = referenced - loaded
    assert not unknown, f"patient_features_v1.sql references unloaded value sets: {sorted(unknown)}"
