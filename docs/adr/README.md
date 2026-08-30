# Architecture Decision Records

Architecture Decision Records (ADRs) capture the significant technical decisions behind this
service: the context that forced a choice, the decision itself, and its consequences — including
the honest downsides we accepted. They exist so that future contributors (human or agent) can
understand *why* the system is shaped this way without re-litigating settled trade-offs, and so
that changing a decision means superseding a record, not silently drifting from it. ADRs are
never deleted; a reversed decision gets a new ADR that references and supersedes the old one.
The spec ([docs/SPEC.md](../SPEC.md)) states *what* v1 is; these records explain *why*.

## Index

| ADR | Title | Status |
|---|---|---|
| [0001](0001-consumption-contract-http-api-plus-readonly-duckdb-attach.md) | Consumption contract is the HTTP API, plus sanctioned read-only DuckDB attach | Accepted |
| [0002](0002-two-layer-canonical-plus-querytime-features.md) | Two-layer model — canonical event tables plus query-time features | Accepted |
| [0003](0003-source-adapter-emits-canonical-rows-not-fhir.md) | SourceAdapter emits canonical rows, not FHIR | Accepted |
| [0004](0004-idempotent-per-patient-replace-and-reparse.md) | Idempotent per-patient replace, raw bundle retention, and reparse | Accepted |
| [0005](0005-date-only-feature-semantics-no-status-columns.md) | Date-only feature semantics — status columns never drive features | Accepted |
| [0006](0006-partial-dates-local-derived-date-utc-ts-precision.md) | Partial dates — source-local derived DATE, UTC timestamp, explicit precision | Accepted |
| [0007](0007-value-sets-committed-json-no-cpt.md) | Value sets as committed, versioned JSON — no CPT | Accepted |
| [0008](0008-deny-by-default-logging.md) | Deny-by-default logging | Accepted |
