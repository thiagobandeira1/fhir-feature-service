# ADR-0008: Deny-by-default logging

## Status

Accepted

## Date

2026-08-30

## Context

All data in this repo is synthetic (Synthea), so nothing here is actually PHI. We treat it as if
it were, for two reasons: the same code paths are meant to host a MIMIC-IV adapter later
(MIMIC-IV is real, de-identified but access-controlled data), and "healthcare-grade hygiene on
synthetic data" is an explicit goal — the habits are the deliverable.

The standard failure mode is not a deliberate `log.info(patient)`; it is incidental leakage:
an exception message that interpolates a resource, a validation error that echoes the offending
value, a debug log of a raw bundle path containing a patient name. Blocklist approaches
("scrub these fields") lose to this by construction — the leak is always a field nobody listed.

## Decision

Logging is **deny-by-default**: a structlog processor drops every event key that is not on an
explicit allowlist (request ids, patient_id, source, action, counts, durations, issue codes,
json_pointers — identifiers and metrics, never clinical values or demographics). Adding a new
loggable key is a code change to the allowlist, reviewable in a PR.

The same posture extends to every output surface:

- **Errors**: RFC 9457 `application/problem+json` responses that never echo resource content —
  a 422 says *what rule* failed and *where* (`json_pointer`), never the offending value.
- **Warnings and audit**: `ingest_log` warnings carry `{code, json_pointer}` only — locations
  and stable snake_case codes, never values. The adapter conformance suite enforces the same
  rule on adapter-emitted warnings.
- **Parsing scope**: the Patient extractor never parses name, telecom, identifiers, photo, or
  contact — minimum-necessary at the parser boundary means unparsed fields *cannot* appear in
  logs, errors, or responses, because they never enter the process's data model.

The control is tested, not asserted: a log-safety test ingests a fixture laced with sentinel
values (names, birthdates, file paths), captures all structured log output for the full ingest,
and fails if any sentinel appears.

## Consequences

- **Debugging is harder on purpose.** When a bundle fails to parse, the log says
  `invalid_datetime` at `/entry/42/resource/onsetDateTime` — not the malformed value. The
  operator must open the raw bundle (retained per ADR-0004) to see it. That extra step is the
  cost of the guarantee.
- The allowlist is a bottleneck by design; every new subsystem's logging needs an allowlist PR,
  and lazy workarounds (stuffing data into an allowed key like `action`) remain possible. The
  sentinel test only catches leaks through fields the fixture seeds — it is a tripwire, not a
  proof.
- Third-party log output (uvicorn access logs, library warnings) is outside the structlog
  pipeline and must be configured separately; access logs are kept to method/path/status, and
  paths never contain names because patient ids are Synthea UUIDs.
- The never-parse rule for Patient fields means the service genuinely cannot serve names — the
  roster endpoint returns ids only. Downstream consumers wanting display names must get them
  elsewhere; that is a feature, not a gap, for repo 1 of 7.
- On synthetic data this rigor is strictly performative today; the payoff comes when the MIMIC
  adapter lands and the discipline is already load-bearing.
