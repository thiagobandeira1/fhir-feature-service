# ADR-0007: Value sets as committed, versioned JSON — no CPT

## Status

Accepted

## Date

2026-08-30

## Context

Feature logic needs code lists: which SNOMED codes mean "diabetes", which LOINC codes are HbA1c,
which RxNorm codes are statins. The industry answer is a terminology service or VSAC downloads,
but both are wrong for this repo: a terminology service is explicitly a non-goal ("not a FHIR
server"), VSAC requires a UMLS license and network access at runtime, and either would make
feature outputs depend on an external moving target — fatal for golden tests that pin feature
rows at fixed dates.

Separately, HEDIS and HCC logic in the wild leans heavily on CPT procedure codes, but CPT is
AMA-licensed content that cannot be committed to a public portfolio repository.

## Decision

Value sets are **committed, versioned JSON files** in
`src/fhir_features/features/value_sets/`, loaded into the `value_set_members` table at startup.
v1 ships sixteen sets: diabetes/hypertension/ascvd/ckd/chf/copd (SNOMED), statin (RxNorm),
hba1c/bp/bmi/tobacco-status/fobt-fit (LOINC), mammogram/colonoscopy/retinal-exam (procedure
codes), flu vaccine (CVX).

A CalVer `valuesets_version` is stamped on every feature response, so any downstream artifact
(a P3 training run, a P1 gap report) records exactly which code lists produced it. The feature
dictionary at `/v1/features/schema` links each feature to its `value_set_id`, and a contract
test asserts every referenced set exists.

**No CPT codes anywhere.** v1 value sets are SNOMED/LOINC/RxNorm/CVX only. This is workable
because Synthea encodes procedures in SNOMED; the `resource_codings` side table still preserves
every raw system URI (unmapped systems become `OTHER:<uri>`), so nothing is thrown away — CPT is
simply never curated into a value set.

## Consequences

- **These are demo-grade placeholder sets, not licensed NCQA/VSAC artifacts.** They were curated
  against Synthea's actual code usage, not clinical review. Real HEDIS/HCC work requires
  licensed sets; this is stated in the README and the feature dictionary rather than hidden.
- No CPT means any consumer processing real-world claims (which speak CPT/ICD-10-CM) cannot use
  these procedure value sets as-is. P4's channel works here only because `claim_diagnoses`
  resolves to SNOMED-coded Conditions.
- Committed JSON is fully reproducible and reviewable — a value-set change is a diff in a PR,
  and golden feature tests fail loudly when a code list edit changes outputs. The flip side:
  updates are manual. Nothing tracks upstream terminology releases; the sets will drift stale
  silently unless someone re-curates them.
- Loading at startup means a value-set edit requires a restart, and the JSON files are trusted
  input (schema-validated at load, but not clinically validated).
- CalVer on `valuesets_version` intentionally decouples code-list churn from `feature_version`:
  the same feature SQL over different code lists is a data change, not a semantic change. Both
  versions must be read together to reproduce a historical result.
