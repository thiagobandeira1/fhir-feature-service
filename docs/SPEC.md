# SPEC — fhir-feature-service (P6)

> Status: **approved v1** · Feature version: `v1` · Produced by spec-driven development with a
> 3-lens design panel (data-engineering, consumer-API, compliance-ops) + adversarial critique +
> synthesis. Key decisions are recorded as ADRs in `docs/adr/`.

## 1. Purpose

A FastAPI microservice that ingests **Synthea FHIR R4 patient bundles** (one patient per bundle)
and normalizes them into a **two-layer DuckDB model**:

1. **Canonical clinical-event tables** — lossless-enough, per-resource rows (the event-level truth).
2. **A versioned patient feature record** — computed **at query time** from the canonical tables
   for any `as_of` date (leakage-free by construction).

It is the data foundation for four downstream consumers:

| Consumer | Need | Contract |
|---|---|---|
| P1 HEDIS care-gap agent | Event-level truth: conditions, observations (BP/HbA1c), procedures, meds, immunizations with codes + dates | `GET /v1/patients/{id}/record` |
| P3 rising-risk model | Leakage-free point-in-time feature rows at any historical `as_of` | `GET /v1/features?as_of=` (paged) |
| P4 HCC coder | Claims-shaped diagnosis history (code + service date + sequence) | `GET /v1/patients/{id}/record` (claim_diagnoses section) |
| P7 dashboard | One fixed panel rollup | `GET /v1/panel/summary` |

The **SourceAdapter** boundary (a canonical intermediate representation, not FHIR) lets a future
**local-only MIMIC-IV adapter** plug into the same schema. MIMIC ships **interface-only** in this
repo: a typed Protocol stub + an executable conformance suite **inside the installed package**
(`fhir_features.testing`), so the later MIMIC repo can `pip install` this wheel and must pass the
identical suite. No MIMIC data, DDL, or row counts are ever committed.

## 2. Goals

1. Ingest Synthea FHIR R4 bundles via one FastAPI endpoint and a CLI; normalize into the two-layer model.
2. Serve all four consumers over HTTP as the declared contract (read-only DuckDB attach is the
   sanctioned local bulk path — ADR-0001).
3. Every feature is **strictly date-derived** relative to `as_of` (no ingest-time status snapshots):
   an event after `as_of` can never influence a feature at `as_of`. Proven by golden tests at two
   pinned dates.
4. Idempotent, replayable ingestion: sha256-keyed no-op detection, transactional per-patient
   replace, raw bundle retention, and a `reparse` CLI command.
5. Correct code-system and date handling: raw system URIs preserved; normalized short names
   (SNOMED/LOINC/RXNORM/CVX/ICD10CM); UTC timestamps **plus** a DATE derived from the
   source-local value (never post-UTC-shift) with an explicit `date_precision` marker.
6. Machine-readable feature contract at `GET /v1/features/schema`, backed by a code registry
   snapshot-tested against the actual SQL output (cannot drift).
7. Healthcare-grade hygiene on synthetic data: deny-by-default structlog allowlist logging with a
   sentinel-name log-safety test; RFC 9457 problem+json errors that never echo resource content;
   value sets as committed versioned JSON.
8. Portfolio-quality repo: OpenAPI snapshot, mermaid architecture diagram, <10-minute quickstart
   (three `uv run` commands), ADRs, conventional commits, Dockerfile (build deferred), ruff +
   mypy strict + pytest green in CI.

## 3. Non-goals

- **MIMIC-IV adapter implementation** — Protocol stub + conformance suite only.
- **HEDIS/HCC/risk computation** — no measure verdicts, not even convenience flags
  (`bp_controlled`, `on_statin`, `tobacco_user` were explicitly cut: they leak measure semantics
  P1 owns; descriptive fields only).
- **Being a FHIR server** — no search/CRUD/$operations/profile validation/terminology service.
- **Async jobs, bulk export endpoints, Prometheus, /readyz, cohort/OLAP engines** — cut as
  overengineering for repo 1 of 7.
- **Auth/multi-tenancy/TLS/cloud deploy** — binds `127.0.0.1` by default.
- **Parsing CarePlan, DiagnosticReport, DocumentReference, ExplanationOfBenefit, Provenance,
  etc.** — counted in `skipped_resource_types`, never crashed on.
- **Materialized feature snapshots** — features are query-time SQL (longitudinal series = multiple
  `as_of` calls).
- **Multi-writer concurrency** — DuckDB single-writer; uvicorn `workers=1`; documented boundary.
- **CPT code lists** — AMA-licensed; v1 value sets are SNOMED/LOINC/RxNorm/CVX only.

## 4. API (v1)

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/ingest/bundle` | Ingest one bundle (exactly one Patient). Idempotent: sha256 no-op / transactional replace. 422 non-Bundle or 0/2+ Patients; 413 over cap (default 20 MB). Returns `{patient_id, source, bundle_hash, action: created\|replaced\|unchanged, resource_counts, skipped_resource_types, warnings:[{code, json_pointer}]}` |
| GET | `/v1/patients` | Paged roster. `limit` (100/max 1000), `offset`, `source`. Deterministic ORDER BY (source, patient_id). |
| GET | `/v1/patients/{id}/record` | **Event-level contract for P1/P4.** Full longitudinal record in one call. Query: `sections` (csv of conditions,observations,procedures,medications,encounters,immunizations,claim_diagnoses), `from`, `to`, `observation_codes` (csv LOINC). Arrays ordered (event_date, id) asc. |
| GET | `/v1/patients/{id}/features` | One feature row at `as_of` (default today UTC). Stamped `{feature_version, valuesets_version}`. |
| GET | `/v1/features` | Bulk paged feature rows at `as_of` for P3/P4. `limit` (500/max 5000), `offset`, `source`. |
| GET | `/v1/features/schema` | Machine-readable feature dictionary (name, type, nullable, description, value_set_id, added_in) + `as_of_semantics`. |
| GET | `/v1/panel/summary` | P7 rollup, computed on the fly: patient_count, avg_age, pct_female, prevalence{diabetes, hypertension, ascvd, ckd, chf, copd}, tobacco_unscreened_count, encounters/ed/inpatient 365d totals. |
| GET | `/healthz` | Liveness+readiness+version handshake: `{status, service_version, schema_version, feature_version}`; 503 problem+json when not ready. |

Errors: RFC 9457 `application/problem+json`; **never echo resource content**.

## 5. Data model

### Canonical tables (grain: one row per source-native id; PK includes `source`)

All canonical tables carry `source` ('synthea'|'mimic'), source-native ids, and `ingested_at`.
Composite key `(source, patient_id)` is the cross-adapter namespacing rule.

- **patients** — birth_date, death_date (from deceasedDateTime/Boolean), sex, race/ethnicity
  (US Core extensions), city, state, postal_code (VARCHAR — leading zeros).
- **encounters** — encounter_class normalized enum `AMB|IMP|EMER|WELLNESS|URGENT|HH|VR|OTHER`
  (mapping covers BOTH v3-ActCode and Synthea lowercase strings, derived from actual fixture
  data; OTHER guarantees reconciliation), type SNOMED coding, start_ts/end_ts (UTC),
  start_date (source-local derived), date_precision.
- **conditions** — primary coding + clinical/verification status (stored for context, **never used
  in feature logic** — leakage), onset_date/abatement_date/recorded_date (source-local derived),
  date_precision.
- **observations** — `Observation.component` **flattened to child rows** with
  `observation_id = '<parent_id>#<component_code>'` (keyed by CODE, not position → re-ingest-stable)
  and `parent_observation_id` set; SBP 8480-6 / DBP 8462-4 within BP panel 85354-9 become directly
  queryable rows sharing a parent. value_num DECIMAL(18,6), value_unit (UCUM), value_code
  (+system), value_text, category, status (final|amended|corrected only).
- **procedures** — code (+all codings to side table), performed_date (performedDateTime or
  performedPeriod.start, source-local), status=completed only.
- **medication_requests** — RxNorm code, authored_date (**the only med field feature logic
  uses**), status/intent stored for display only.
- **immunizations** — CVX code, occurrence_date, status=completed only.
- **claim_diagnoses** — grain (source, claim_id, diagnosis_sequence); resolved from
  `Claim.diagnosis[].diagnosisReference` to in-bundle Conditions; billable_period_start as
  service-date proxy for HCC lookback. P4's claims-shaped channel.
- **resource_codings** — side table for ALL codings of Condition + Procedure (raw URI always
  preserved; normalized short name; `OTHER:<uri>` if unmapped).

### Ops tables

- **raw_bundles** — bundle_hash PK (sha256 of canonicalized JSON), full payload (DuckDB JSON);
  latest per patient; enables `reparse`.
- **ingest_log** — append-only audit: action created|replaced|unchanged|reparsed|failed,
  resource_counts + skipped_resource_types (reconciliation surface), warnings
  `[{code, json_pointer}]` — locations and codes only, never values.
- **schema_migrations** — numbered .sql files, checksummed; runner refuses to start if an applied
  file was edited.

### Reference

- **value_set_members** — loaded at startup from committed JSON
  (`src/fhir_features/features/value_sets/`). v1 sets: diabetes_snomed, hypertension_snomed,
  ascvd_snomed, ckd_snomed, chf_snomed, copd_snomed, statin_rxnorm, hba1c_loinc, bp_loinc,
  bmi_loinc, tobacco_status_loinc, mammogram_proc, colonoscopy_proc, fobt_fit_loinc,
  retinal_exam_proc, flu_vaccine_cvx. `valuesets_version` (CalVer) stamped on every feature
  response. **No CPT (AMA licensing).**

### patient_features (LOGICAL — computed at query time)

One row per (source, patient_id) per requested `as_of`. NOT materialized: a versioned,
`as_of`-parameterized SQL query (`features/sql/patient_features_v1.sql`).

**Inclusion rule (stated once, tested everywhere):** an event counts iff its
source-local-derived DATE ≤ `as_of`.

Columns: source, patient_id, as_of, feature_version, valuesets_version, age_years, sex, race,
ethnicity, is_deceased · chronic flags has_diabetes/has_hypertension/has_ascvd/has_ckd/has_chf/
has_copd (onset_date ≤ as_of AND (abatement NULL OR > as_of) — dates, never clinical_status),
chronic_condition_count · latest_sbp + latest_dbp (**from the SAME parent panel**, never
independently latest) + latest_bp_date, latest_hba1c(+date), latest_bmi(+date) ·
tobacco_status_code (raw SNOMED answer of latest 72166-2; **NULL = never screened** — the gap
signal P1 needs) + date · statin_authored_365d (descriptive, not "on_statin"),
last_statin_authored_date, distinct_meds_authored_365d · last_mammogram_date,
last_colonoscopy_date, last_fobt_fit_date, last_retinal_exam_date, last_flu_immunization_date ·
encounters_365d/90d, ambulatory/wellness/ed/inpatient 365d counts, inpatient_days_365d,
lab_results_365d, days_since_last_encounter.

Versioning: additive columns don't bump `feature_version`; semantic changes do (via ADR).

## 6. FHIR parsing rules

- **Bundle envelope**: hard validation — valid JSON Bundle, exactly one Patient, else 422.
  `entry[].fullUrl` urn:uuid → (type, id) reference map. Unknown resource types counted, never
  crashed on. Dangling references warn + NULL FK.
- **Patient**: id, birthDate, gender, deceased[x], address[0] city/state/postalCode, US Core
  race/ethnicity. **Never parsed: name, telecom, identifiers, photo, contact** (minimum-necessary:
  unparsed fields cannot leak into logs/errors/responses).
- **Dates**: `parse_fhir_datetime() -> (utc_ts, local_date, precision)` where precision ∈
  second|day|month|year. local_date derived from the source-local string BEFORE UTC conversion.
- Resources parsed: Patient, Encounter, Condition, Observation, Procedure, MedicationRequest,
  Immunization, Claim. Everything else: skipped-and-counted.

## 7. Adapter boundary (CIR)

`canonical/models.py`: frozen pydantic v2 row models mirroring canonical tables 1:1 + the unit of
work `PatientRecordSet(source, patient, encounters, conditions, observations, procedures,
medication_requests, immunizations, claim_diagnoses, codings, skipped, warnings)`.

`adapters/base.py`:

```python
class SourceAdapter(Protocol):
    source: ClassVar[str]
    def iter_patient_records(self) -> Iterator[PatientRecordSet]: ...
```

No runtime registry (ceremony for one adapter). `store/loader.py` performs the transactional
per-patient replace for ANY PatientRecordSet. Normalization burden sits ON the adapter by
contract: UTC ts + source-local dates + honest precision, normalized code systems, UCUM units.

`adapters/mimic.py`: interface-only stub — correct signature, env-only config
(`MIMIC_DB_URL`/`MIMIC_CSV_DIR`, validated to resolve outside the repo tree),
NotImplementedError, docstring mapping plan.

`fhir_features/testing/conformance.py`: **AdapterConformanceSuite inside the wheel** — unique ids,
resolvable FKs, valid precision enums, normalized systems, no events before birth, deterministic
across two runs, warnings carry codes/pointers but never values. Synthea passes it in CI; the
future MIMIC repo installs this package and must pass the identical suite.

## 8. Module layout

See repository tree; package `fhir_features` (pinned by pyproject). Key entries: `cli.py`
(`init-db | ingest <dir> | reparse | serve`), `api/` (app factory, RFC 9457 errors, route
modules), `canonical/` (models, codes, dates), `fhir/` (bundle walk + 8 extractors), `adapters/`,
`store/` (db, migrate, migrations/, loader), `features/` (registry, queries, sql, value_sets/),
`testing/conformance.py`.

## 9. Testing strategy

One CI job (ubuntu-latest, py3.12): uv sync --frozen → ruff check + format → mypy strict →
pytest with coverage fail_under=85 → tracked-data-file guard.

1. **Unit**: dates (partial precisions, garbage → warning; the evening-at-−05:00 keeps its local
   calendar date test), codes (URI normalization, OTHER fallback, encounter-class dual mapping),
   bundle (urn:uuid resolution, dangling refs, hard 422 cases), per-extractor fragments (esp. BP
   component flattening: code-keyed child ids stable across re-ingest, SBP/DBP share parent).
2. **Adapter conformance**: in-package suite vs SyntheaAdapter over fixtures; MIMIC stub satisfies
   Protocol under mypy strict.
3. **Integration** on 5–6 persona fixtures: idempotency (ingest twice → unchanged; mutate →
   replaced, no orphans); reparse end-to-end.
4. **Golden feature tests — the trust core**: features at TWO pinned as_of dates vs committed
   JSON, including anti-leakage assertions (2023 as_of cannot see a 2024 admission / later statin /
   later-onset condition). Goldens regenerate only via explicit script → reviewable diffs.
5. **API**: TestClient over tmp DuckDB; every endpoint happy + error paths as problem+json with
   zero resource echo; deterministic ordering; schema-contract test (`/v1/features/schema` ==
   actual SQL columns AND every value_set_id exists); committed openapi.json snapshot.
6. **Log-safety**: structured-log capture over a full ingest asserts no sentinel names/birthdates/
   file paths appear.
7. **Migrations**: fresh-apply matches snapshot; checksum guard trips on edit.

## 10. Risks (accepted, documented)

- Synthea codes in SNOMED; HEDIS/HCC speak CPT/ICD-10-CM — curated value sets are demo-grade
  placeholders for licensed NCQA/VSAC sets (stated in README + feature dictionary).
- Medication features are date-only approximations (no reliable stop dates in Synthea output) —
  `statin_authored_365d` is a recency proxy, not adherence.
- DuckDB single-writer; query-time features scan per request (fine at this scale; materialized
  snapshots are the documented future optimization for MIMIC volume).
- Year/month precision comparisons are optimistic (Jan-1 imputation), kept visible via
  `date_precision`.
- `.gitignore` doesn't stop `git add -f`; CI tracked-file guard is the real control.
