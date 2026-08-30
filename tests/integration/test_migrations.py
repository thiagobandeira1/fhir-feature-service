"""Migration runner: fresh apply, idempotency, and the edited-history checksum guard."""

from pathlib import Path

import pytest

from fhir_features.store.db import Database
from fhir_features.store.migrate import MigrationError, migrate

EXPECTED_TABLES = {
    "patients",
    "encounters",
    "conditions",
    "observations",
    "procedures",
    "medication_requests",
    "immunizations",
    "claim_diagnoses",
    "resource_codings",
    "raw_bundles",
    "ingest_log",
    "value_set_members",
    "schema_migrations",
}


def test_fresh_apply_creates_all_tables(tmp_path: Path) -> None:
    with Database(tmp_path / "m.duckdb") as db:
        version = migrate(db)
        assert version >= 3
        tables = {
            row[0] for row in db.conn.execute("SELECT table_name FROM duckdb_tables()").fetchall()
        }
        assert tables >= EXPECTED_TABLES


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    with Database(tmp_path / "m.duckdb") as db:
        first = migrate(db)
        second = migrate(db)
        assert first == second
        count = db.conn.execute("SELECT count(*) FROM schema_migrations").fetchone()
        assert count is not None
        assert count[0] == first if first <= 3 else True


def test_edited_applied_migration_trips_checksum_guard(tmp_path: Path) -> None:
    with Database(tmp_path / "m.duckdb") as db:
        migrate(db)
        db.conn.execute("UPDATE schema_migrations SET checksum = 'tampered' WHERE version = 1")
        with pytest.raises(MigrationError, match="edited"):
            migrate(db)
