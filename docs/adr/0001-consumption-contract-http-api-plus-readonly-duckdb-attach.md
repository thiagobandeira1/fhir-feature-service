# ADR-0001: Consumption contract is the HTTP API, plus sanctioned read-only DuckDB attach

## Status

Accepted

## Date

2026-08-30

## Context

Four downstream consumers need this service's data, with very different access shapes:

- P1 (HEDIS care-gap agent) needs the full longitudinal event record for one patient at a time.
- P3 (rising-risk model) needs bulk, leakage-free feature rows at historical `as_of` dates —
  potentially thousands of patients per training run.
- P4 (HCC coder) needs claims-shaped diagnosis history per patient.
- P7 (dashboard) needs one fixed panel rollup.

The tension is between P3's bulk-training access pattern and everything else. Options considered:

1. HTTP-only, with async bulk-export jobs (FHIR `$export`-style NDJSON).
2. HTTP-only, paged, no bulk path at all.
3. HTTP as the declared contract, plus a documented local escape hatch: consumers on the same
   machine may `ATTACH` the DuckDB file **read-only** for bulk reads.

Async job infrastructure (job tables, polling endpoints, artifact storage) was judged
overengineering for repo 1 of 7 and was cut in the spec's non-goals. Pure paged HTTP makes P3's
training loop slow and chatty for no compliance benefit — all data here is synthetic Synthea
output and all consumers are local repos in the same portfolio.

## Decision

The versioned HTTP API (`/v1/...`) is the **declared contract**: paged rosters, per-patient
record, per-patient and bulk feature endpoints, panel summary, and a machine-readable feature
schema. Additionally, read-only `ATTACH` of the DuckDB database file is the **sanctioned local
bulk path** for consumers that need whole-table scans (primarily P3 training). "Sanctioned"
means: documented in the README, covered by the schema-migration discipline, and constrained to
`READ_ONLY` attach mode.

The HTTP layer remains the only write path. DuckDB is single-writer, so the service runs with
`workers=1` and bulk readers must attach read-only to avoid lock contention with ingestion.

## Consequences

- The canonical and feature-supporting table schemas become a de facto public interface, not just
  an implementation detail. Renaming a column is a breaking change for attach consumers even if
  the HTTP API is untouched. Mitigation: numbered, checksummed migrations
  (`schema_migrations`) and the feature-schema snapshot test make drift visible, but the
  discipline is on us — nothing mechanically stops an attach consumer from depending on an
  "internal" column.
- Two contracts must be kept coherent: what `/v1/features` returns and what a SQL consumer
  computes from the same tables. The shared `patient_features_v1.sql` file is the single source;
  attach consumers who write their own SQL are on their own.
- No bulk HTTP export means a remote (non-local) consumer has only paged endpoints. Acceptable
  now (everything is local); would need revisiting before any networked deployment.
- Lock semantics are a real operational footgun: a consumer attaching read-write by accident
  blocks ingestion. Documented, not enforced by code.
- We avoid building and testing an async job subsystem, which keeps the service surface small
  enough to reach portfolio quality (OpenAPI snapshot, golden tests) in one repo.
