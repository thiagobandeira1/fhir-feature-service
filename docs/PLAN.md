# Build plan — fhir-feature-service

Dependency-ordered stages; each lands with its tests. TDD on core logic.

- [ ] **A. Foundation** (fixes all interfaces): `config`, `logging_setup`, `canonical/models`
      (CIR), `canonical/dates`, `canonical/codes`, `store/db`, `store/migrate`,
      `store/migrations/*.sql` + unit tests (dates, codes, migrations).
- [ ] **B. Extraction layer**: `fhir/bundle.py` (envelope validation, urn:uuid map, sha256),
      8 extractors (patient reference-pattern first, others follow) + per-extractor unit tests,
      incl. BP component flattening.
- [ ] **C. Reference data**: value-set JSON files grounded against actual Synthea output codes
      (verified via the generated CSVs), `valuesets_version` stamping.
- [ ] **D. Persistence**: `store/loader.py` transactional per-patient replace + ingest_log;
      `adapters/base.py` Protocol, `adapters/synthea.py`, `adapters/mimic.py` stub;
      `testing/conformance.py` in-wheel suite + contract tests.
- [ ] **E. Features**: `features/registry.py`, `features/sql/patient_features_v1.sql`,
      `features/queries.py` + golden tests at two pinned as_of dates with anti-leakage asserts.
- [ ] **F. API + CLI**: app factory, RFC 9457 errors, routes, schemas, `cli.py`
      (init-db | ingest | reparse | serve) + API/integration/log-safety/openapi-snapshot tests.
- [ ] **G. Review gate**: multi-agent adversarial code review; apply confirmed fixes.
- [ ] **H. Ship**: README (mermaid diagram, quickstart, consumer matrix), Dockerfile,
      .gitattributes, ADRs 0001–0008, PROVENANCE.md, openapi snapshot, gh repo create + push,
      CI green, branch/PR workflow.
