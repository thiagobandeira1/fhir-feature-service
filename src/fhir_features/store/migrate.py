"""Ordered SQL migration runner with a checksum ledger.

Migrations are numbered ``NNNN_name.sql`` files shipped as package data. The runner refuses to
start if a previously applied file's content changed (checksum mismatch) — applied migrations
are immutable history.
"""

import hashlib
from datetime import UTC, datetime
from importlib import resources

from fhir_features.logging_setup import get_logger
from fhir_features.store.db import Database

log = get_logger(__name__)


class MigrationError(RuntimeError):
    """A migration cannot be applied (bad name, edited history, or SQL failure)."""


def _load_migration_files() -> list[tuple[int, str, str]]:
    """Return sorted (version, name, sql) from the package's migrations directory."""
    out: list[tuple[int, str, str]] = []
    root = resources.files("fhir_features.store") / "migrations"
    for entry in root.iterdir():
        if not entry.name.endswith(".sql"):
            continue
        prefix, _, _ = entry.name.partition("_")
        try:
            version = int(prefix)
        except ValueError as exc:
            raise MigrationError(f"migration file lacks numeric prefix: {entry.name}") from exc
        out.append((version, entry.name, entry.read_text(encoding="utf-8")))
    out.sort()
    versions = [v for v, _, _ in out]
    if len(set(versions)) != len(versions):
        raise MigrationError("duplicate migration version numbers")
    return out


def migrate(db: Database) -> int:
    """Apply pending migrations in order; return the current schema version."""
    conn = db.conn
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    INTEGER NOT NULL PRIMARY KEY,
            name       VARCHAR NOT NULL,
            checksum   VARCHAR NOT NULL,
            applied_at TIMESTAMP NOT NULL
        )
        """
    )
    applied: dict[int, tuple[str, str]] = {
        row[0]: (row[1], row[2])
        for row in conn.execute("SELECT version, name, checksum FROM schema_migrations").fetchall()
    }
    current = 0
    for version, name, sql in _load_migration_files():
        checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        if version in applied:
            if applied[version][1] != checksum:
                raise MigrationError(
                    f"applied migration {version} ({applied[version][0]}) was edited; "
                    "migrations are immutable — add a new one instead"
                )
            current = version
            continue
        with db.transaction() as tx:
            tx.execute(sql)
            tx.execute(
                "INSERT INTO schema_migrations VALUES (?, ?, ?, ?)",
                [version, name, checksum, datetime.now(UTC)],
            )
        log.info("migration_applied", migration_version=version)
        current = version
    return current
