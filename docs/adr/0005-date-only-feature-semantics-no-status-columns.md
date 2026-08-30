# ADR-0005: Date-only feature semantics — status columns never drive features

## Status

Accepted

## Date

2026-08-30

## Context

The rising-risk model (P3) trains on historical feature rows. The classic failure mode is
temporal leakage: a feature computed "as of 2023-06-01" that was secretly influenced by
information recorded later. FHIR resources invite exactly this mistake, because their status
fields (`Condition.clinicalStatus`, `MedicationRequest.status`) describe the state **at export
time**, not at any historical date. A condition marked `resolved` in a 2025 export was still
active in 2023; using clinicalStatus in a 2023 feature row leaks 2025 knowledge.

A related temptation is convenience flags — during design, `bp_controlled`, `on_statin`, and
`tobacco_user` were proposed and explicitly cut. Each encodes measure semantics (thresholds,
adherence definitions, screening interpretations) that downstream consumers own: P1 owns HEDIS
logic, P3 owns risk definitions.

## Decision

Every feature is **strictly date-derived** relative to `as_of`. The single inclusion rule: an
event counts iff its source-local-derived DATE ≤ `as_of` (ADR-0006 defines that date). Concretely:

- Chronic condition flags (`has_diabetes`, etc.) use `onset_date ≤ as_of AND (abatement_date IS
  NULL OR abatement_date > as_of)` — dates, never `clinical_status`. Status and verification
  fields are stored on `conditions` for display context only.
- Medication features are `statin_authored_365d`, `last_statin_authored_date`, and
  `distinct_meds_authored_365d` — counts and recency over `authored_date`, the only medication
  field feature logic reads. There is no `on_statin`.
- Tobacco is the raw SNOMED answer code of the latest 72166-2 observation at or before `as_of`,
  with NULL meaning **never screened** — the gap signal P1 needs — not an interpreted
  `tobacco_user` boolean.
- No measure verdicts of any kind; descriptive fields only.

The property is proven by golden tests at two pinned `as_of` dates, including explicit
anti-leakage assertions (a 2023 `as_of` cannot see a 2024 admission, a later statin, or a
later-onset condition).

## Consequences

- **Medication features are recency proxies, not adherence.** Synthea output has no reliable
  stop dates, so `statin_authored_365d` says "a statin was prescribed recently", not "the
  patient is on a statin". Consumers who need adherence must build it themselves — deliberately.
- Abatement-date logic undercounts resolved-then-relapsed conditions and overcounts conditions
  whose resolution was recorded only as a status change without an abatement date. We accept
  the bias in exchange for reproducibility at any `as_of`.
- Downstream consumers do more work: P1 must implement its own control/adherence logic from
  event-level data. That duplication is intentional — a leaked convenience flag would be used
  precisely because it is convenient.
- The stored-but-unused status columns are a standing temptation; the guard is code review plus
  the golden anti-leakage tests, not a mechanical restriction.
- Rows with garbage or missing required dates are dropped (with a recorded ParseIssue) rather
  than included statelessly — under date-only semantics an undated event is unusable, so the
  drop is the honest choice, at the cost of losing those events entirely.
