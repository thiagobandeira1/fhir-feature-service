# Feature dictionary — `v1`

> **Generated file — do not edit.** Regenerate with
> `uv run python scripts/gen_feature_dictionary.py`. The machine-readable equivalent is
> `GET /v1/features/schema`; a schema-contract test pins both to the actual SQL columns.

- **feature_version:** `v1` — stamped on every feature response. Additive
  columns do not bump it; semantic changes do (via ADR).
- **valuesets_version:** `2026.08` (CalVer) — version of the committed value-set
  JSON, also stamped on every feature response.
- **as_of semantics:** event included iff source-local event date <= as_of. Features are computed at query time from the
  canonical event tables, so an event dated after `as_of` can never influence a feature at
  `as_of` (leakage-free by construction; proven by golden tests at two pinned dates).
- **Value-set caveat:** the value sets referenced below are **demo-grade** curated sets built
  from public code systems (SNOMED CT, LOINC, RxNorm, CVX) and cross-checked against the
  generated Synthea data. They are **not** NCQA HEDIS / VSAC licensed sets; a real measure
  program would swap in licensed sets.

| # | Name | Type | Nullable | Value set | Description |
|---|------|------|----------|-----------|-------------|
| 1 | `source` | string | no | — | Data source token ('synthea' \| 'mimic'). |
| 2 | `patient_id` | string | no | — | Source-native patient id. |
| 3 | `as_of` | date | no | — | Echoed request parameter; all logic is relative to it. |
| 4 | `age_years` | integer | yes | — | Floor whole years between birth_date and as_of. |
| 5 | `sex` | string | no | — | male \| female \| other \| unknown. |
| 6 | `race` | string | yes | — | US Core race extension text. |
| 7 | `ethnicity` | string | yes | — | US Core ethnicity extension text. |
| 8 | `is_deceased` | boolean | no | — | death_date <= as_of. |
| 9 | `has_diabetes` | boolean | no | `diabetes_snomed` | Any diabetes condition with onset <= as_of and no abatement <= as_of. Date-derived; clinical_status is never consulted. |
| 10 | `has_hypertension` | boolean | no | `hypertension_snomed` | Same pattern. |
| 11 | `has_ascvd` | boolean | no | `ascvd_snomed` | Same pattern (statin-measure input). |
| 12 | `has_ckd` | boolean | no | `ckd_snomed` | Same pattern. |
| 13 | `has_chf` | boolean | no | `chf_snomed` | Same pattern. |
| 14 | `has_copd` | boolean | no | `copd_snomed` | Same pattern. |
| 15 | `chronic_condition_count` | integer | no | — | Count of TRUE chronic flags above. |
| 16 | `latest_sbp` | number | yes | `bp_loinc` | Most recent systolic (LOINC 8480-6) on/before as_of. |
| 17 | `latest_dbp` | number | yes | `bp_loinc` | Diastolic (8462-4) from the SAME panel as latest_sbp — never independently latest. |
| 18 | `latest_bp_date` | date | yes | — | Date of that panel. |
| 19 | `latest_hba1c` | number | yes | `hba1c_loinc` | Most recent HbA1c % (4548-4). |
| 20 | `latest_hba1c_date` | date | yes | — | Date of that result. |
| 21 | `latest_bmi` | number | yes | `bmi_loinc` | Most recent BMI kg/m2 (39156-5). |
| 22 | `latest_bmi_date` | date | yes | — | Date of that result. |
| 23 | `tobacco_status_code` | string | yes | `tobacco_status_loinc` | Raw SNOMED answer of the latest tobacco screening (72166-2). NULL = never screened — the gap signal. Descriptive: P1 owns any verdict. |
| 24 | `tobacco_status_date` | date | yes | — | Date of that screening. |
| 25 | `statin_authored_365d` | boolean | no | `statin_rxnorm` | Any statin order authored in (as_of-365d, as_of]. A recency proxy, NOT adherence (Synthea has no reliable stop dates); named descriptively on purpose. |
| 26 | `last_statin_authored_date` | date | yes | `statin_rxnorm` | Most recent statin order on/before as_of. |
| 27 | `distinct_meds_authored_365d` | integer | no | — | Distinct RxNorm codes authored in the window (date-derived med burden). |
| 28 | `last_mammogram_date` | date | yes | `mammogram_proc` | Latest mammography. |
| 29 | `last_colonoscopy_date` | date | yes | `colonoscopy_proc` | Latest colonoscopy. |
| 30 | `last_fobt_fit_date` | date | yes | `fobt_fit_loinc` | Latest stool-based screening lab. |
| 31 | `last_retinal_exam_date` | date | yes | `retinal_exam_proc` | Latest retinal exam. |
| 32 | `last_flu_immunization_date` | date | yes | `flu_vaccine_cvx` | Latest influenza vaccine. |
| 33 | `encounters_365d` | integer | no | — | Encounters starting in (as_of-365d, as_of]. |
| 34 | `encounters_90d` | integer | no | — | Encounters starting in (as_of-90d, as_of]. |
| 35 | `ambulatory_visits_365d` | integer | no | — | Class AMB in the 365d window. |
| 36 | `wellness_visits_365d` | integer | no | — | Class WELLNESS in the window. |
| 37 | `ed_visits_365d` | integer | no | — | Class EMER in the window. |
| 38 | `inpatient_admits_365d` | integer | no | — | Class IMP starting in the window. |
| 39 | `inpatient_days_365d` | integer | no | — | Sum of LOS days for IMP encounters starting in the window (end date via UTC ts — documented one-day approximation). |
| 40 | `lab_results_365d` | integer | no | — | Top-level laboratory observations in the window. |
| 41 | `days_since_last_encounter` | integer | yes | — | as_of - latest start_date; NULL if none. |
