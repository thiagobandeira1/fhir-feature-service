# ADR-0004: Idempotent per-patient replace, raw bundle retention, and reparse

## Status

Accepted

## Date

2026-08-30

## Context

Synthea bundles arrive one patient per bundle, via an HTTP endpoint and a CLI that walks a
directory. Both paths will inevitably re-submit the same files: reruns of `ingest <dir>`,
retried POSTs, regenerated fixture sets. Ingestion must therefore be safe to replay. Separately,
parser bugs are a certainty in a service whose whole job is parsing; fixing one must not require
the original source files, which may have moved.

Alternatives considered for the write model:

- **Append-only with soft-delete/versioning**: full history, but every read query needs
  "latest version" predicates, and the feature SQL becomes materially harder to keep leakage-free.
- **Upsert per resource**: leaves orphans when a re-submitted bundle *drops* a resource that the
  previous version contained.
- **Transactional per-patient replace**: delete-then-insert all rows for `(source, patient_id)`
  in one transaction. Simple invariant: the canonical tables always reflect exactly the latest
  accepted bundle per patient.

## Decision

Ingestion is idempotent and replayable via three mechanisms:

1. **sha256 no-op detection.** The bundle's canonicalized JSON is hashed; if `bundle_hash`
   matches what is already stored for that patient, the request is a no-op returning
   `action: unchanged`. Byte-identical replays cost one hash and one lookup.
2. **Transactional per-patient replace.** A changed bundle deletes and re-inserts every
   canonical row for `(source, patient_id)` in a single transaction, returning
   `action: replaced` (or `created` for a new patient). No partial states, no orphans —
   verified by integration tests that mutate a bundle and re-ingest.
3. **Raw retention + reparse.** `raw_bundles` keeps the latest full payload per patient (DuckDB
   JSON, keyed by `bundle_hash`). The `reparse` CLI command re-runs the current parser over
   stored payloads, so a parser fix can repopulate canonical tables without the original files.

Every action lands in `ingest_log`, an append-only audit trail carrying
`created|replaced|unchanged|reparsed|failed`, resource counts, `skipped_resource_types`, and
warnings as `{code, json_pointer}` — locations and codes only, never values (see ADR-0008).

## Consequences

- Replace semantics mean **no history**: a re-ingested patient's previous canonical rows are
  gone. `ingest_log` records that a replace happened but not what changed. Acceptable for
  synthetic data; a real clinical system would need bitemporal storage.
- Storing only the latest raw bundle per patient bounds storage but limits `reparse` to the
  current state of the world — it cannot reconstruct what features looked like under an older
  bundle.
- The sha256 no-op check is exact-bytes-after-canonicalization: a semantically identical bundle
  with reordered entries still triggers a full (harmless but wasted) replace unless
  canonicalization normalizes ordering.
- Delete-then-insert inside one transaction relies on DuckDB's single-writer model
  (`workers=1`); the design does not survive concurrent writers and does not try to.
- `reparse` after a parser fix silently changes feature outputs for already-ingested patients.
  That is the point, but golden feature tests must be regenerated and reviewed as part of any
  such fix.
