"""Command-line interface: ``init-db | ingest <dir> | reparse | serve``.

The CLI owns directory ingestion (there is deliberately no server-side directory endpoint —
an arbitrary-path ingest API is an attack surface; see SPEC non-goals).
"""

import argparse
import json
import sys
from pathlib import Path

import fhir_features
from fhir_features.adapters.synthea import (
    SyntheaBundleAdapter,
    load_bundle_file,
    record_set_from_bundle,
)
from fhir_features.config import get_settings
from fhir_features.features.value_sets import load_value_sets
from fhir_features.fhir.bundle import BundleValidationError, canonical_bundle_hash
from fhir_features.logging_setup import configure_logging, get_logger
from fhir_features.store.db import Database
from fhir_features.store.loader import bundle_already_loaded, load_patient, record_failed_ingest
from fhir_features.store.migrate import migrate
from fhir_features.store.reference import sync_value_sets

log = get_logger(__name__)


def _open_db() -> Database:
    db = Database(get_settings().db_path)
    migrate(db)
    bundle = load_value_sets()
    sync_value_sets(db, bundle)
    return db


def cmd_init_db(_: argparse.Namespace) -> int:
    with _open_db() as db:
        row = db.conn.execute("SELECT max(version) FROM schema_migrations").fetchone()
        print(f"database ready (schema version {row[0] if row else '?'})")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    bundle_dir = Path(args.directory)
    if not bundle_dir.is_dir():
        print(f"error: {bundle_dir} is not a directory", file=sys.stderr)
        return 2
    adapter = SyntheaBundleAdapter(bundle_dir)
    files = adapter.bundle_files()
    if not files:
        print(f"error: no .json/.json.gz bundles in {bundle_dir}", file=sys.stderr)
        return 2
    ok = failed = unchanged = 0
    with _open_db() as db:
        for path in files:
            try:
                payload = load_bundle_file(path)
                record_set = record_set_from_bundle(payload)
                bundle_hash = canonical_bundle_hash(payload)
                if bundle_already_loaded(db, bundle_hash):
                    unchanged += 1
                    continue
                load_patient(
                    db,
                    record_set,
                    bundle_hash=bundle_hash,
                    raw_payload=json.dumps(payload, separators=(",", ":")),
                    service_version=fhir_features.__version__,
                )
                ok += 1
            except (BundleValidationError, ValueError, OSError) as exc:
                code = exc.code if isinstance(exc, BundleValidationError) else "unreadable_file"
                record_failed_ingest(
                    db,
                    source="synthea",
                    bundle_hash=None,
                    error_code=code,
                    service_version=fhir_features.__version__,
                )
                failed += 1
                log.info("ingest_failed", action="failed", warning_codes=[code])
    print(f"ingested {ok} bundle(s), {unchanged} unchanged, {failed} failed of {len(files)}")
    return 0 if failed == 0 else 1


def cmd_reparse(_: argparse.Namespace) -> int:
    """Rebuild canonical tables from retained raw bundles (after extractor fixes)."""
    ok = failed = 0
    with _open_db() as db:
        hashes = [
            row[0]
            for row in db.conn.execute(
                "SELECT bundle_hash FROM raw_bundles ORDER BY source, patient_id"
            ).fetchall()
        ]
        for bundle_hash in hashes:
            row = db.conn.execute(
                "SELECT payload FROM raw_bundles WHERE bundle_hash = ?", [bundle_hash]
            ).fetchone()
            if row is None:
                continue
            try:
                payload = json.loads(row[0])
                record_set = record_set_from_bundle(payload)
                load_patient(
                    db,
                    record_set,
                    bundle_hash=bundle_hash,
                    raw_payload=None,  # payload already retained
                    service_version=fhir_features.__version__,
                    reparse=True,
                )
                ok += 1
            except (BundleValidationError, ValueError) as exc:
                code = exc.code if isinstance(exc, BundleValidationError) else "reparse_error"
                record_failed_ingest(
                    db,
                    source="synthea",
                    bundle_hash=bundle_hash,
                    error_code=code,
                    service_version=fhir_features.__version__,
                )
                failed += 1
    print(f"reparsed {ok} bundle(s), {failed} failed")
    return 0 if failed == 0 else 1


def cmd_serve(_: argparse.Namespace) -> int:
    import uvicorn

    from fhir_features.api.app import create_app

    settings = get_settings()
    # workers=1 is deliberate: DuckDB is single-writer (see ADR-0002 / SPEC non-goals).
    uvicorn.run(create_app(settings), host=settings.bind_host, port=settings.bind_port)
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="fhir-features", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="create/upgrade the DuckDB schema").set_defaults(
        func=cmd_init_db
    )
    ingest = sub.add_parser("ingest", help="ingest a directory of bundle files")
    ingest.add_argument("directory", help="directory containing *.json / *.json.gz bundles")
    ingest.set_defaults(func=cmd_ingest)
    sub.add_parser(
        "reparse", help="rebuild canonical tables from retained raw bundles"
    ).set_defaults(func=cmd_reparse)
    sub.add_parser("serve", help="run the API server").set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
