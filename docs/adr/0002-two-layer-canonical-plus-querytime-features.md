# ADR-0002: Two-layer model — canonical event tables plus query-time features

## Status

Accepted

## Date

2026-08-30

## Context

Consumers need two different views of the same patients: P1/P4 need event-level truth
(individual conditions, observations, procedures, meds with codes and dates), while P3 needs a
point-in-time feature row per patient at an arbitrary historical `as_of` date, guaranteed free of
temporal leakage (an event after `as_of` must never influence the row).

Options considered:

1. **Single materialized feature table**, refreshed at ingest time. Fast to serve, but every
   `as_of` requires either re-ingestion or a snapshot-per-date scheme, and ingest-time status
   snapshots ("active condition", "current medication") bake leakage in permanently.
2. **Feature store with precomputed snapshots per date grid.** Real infrastructure cost, storage
   growth, and a cache-invalidation problem whenever value sets or feature SQL change.
3. **Two layers: canonical clinical-event tables (the stored truth) + a versioned,
   `as_of`-parameterized SQL query that computes the feature row on demand.**

## Decision

Adopt option 3. Canonical tables (`patients`, `encounters`, `conditions`, `observations`,
`procedures`, `medication_requests`, `immunizations`, `claim_diagnoses`, `resource_codings`)
store per-resource rows keyed by `(source, <native id>)`. The `patient_features` row is
**logical**: `features/sql/patient_features_v1.sql` computes it at query time for any `as_of`,
under one inclusion rule stated once and tested everywhere — an event counts iff its
source-local-derived DATE ≤ `as_of`.

Leakage-freedom is therefore a structural property (the query cannot see the future because the
predicate excludes it), proven by golden tests at two pinned `as_of` dates with explicit
anti-leakage assertions. Feature versioning: additive columns do not bump `feature_version`;
semantic changes do, via a new ADR.

## Consequences

- **Query-time features re-scan the canonical tables on every request.** `/v1/features` at
  `limit=5000` runs the full feature SQL per page. Fine at Synthea portfolio scale on DuckDB's
  columnar engine; it will not be fine at MIMIC-IV volume. Materialized snapshots are the
  documented future optimization, deliberately deferred (spec §10).
- Longitudinal feature series require N calls with N `as_of` values — there is no "give me
  monthly rows for 2020–2024" endpoint. Acceptable for P3's training loop; clumsy for anything
  interactive.
- The feature contract lives in SQL, so it must be pinned by tests, not types:
  `/v1/features/schema` is snapshot-tested against the actual SQL output columns so the
  machine-readable dictionary cannot drift from reality.
- Changing feature semantics is cheap (edit one SQL file, regenerate goldens, bump version) —
  the flip side is that a careless SQL edit changes historical answers retroactively, since
  nothing is materialized. The golden tests at pinned dates are the only guard.
- Canonical tables must be complete enough for features we haven't written yet; that pushes us
  toward keeping raw codes (`resource_codings`) and honest date precision rather than
  pre-digesting, which costs storage but has already paid for itself twice in this design.
