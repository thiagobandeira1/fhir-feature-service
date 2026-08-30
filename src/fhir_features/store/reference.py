"""Load committed value-set JSON into the ``value_set_members`` reference table."""

from typing import TYPE_CHECKING

from fhir_features.store.db import Database

if TYPE_CHECKING:
    from fhir_features.features.value_sets import ValueSetBundle


def sync_value_sets(db: Database, bundle: "ValueSetBundle") -> int:
    """Replace the reference table's contents with the committed bundle; return member count."""
    with db.transaction() as conn:
        conn.execute("DELETE FROM value_set_members")
        conn.executemany(
            "INSERT INTO value_set_members VALUES (?, ?, ?, ?, ?)",
            [
                (m.value_set_id, m.code_system, m.code, m.display, bundle.version)
                for m in bundle.members
            ],
        )
    return len(bundle.members)
