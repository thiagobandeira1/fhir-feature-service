# ADR-0003: SourceAdapter emits canonical rows, not FHIR

## Status

Accepted

## Date

2026-08-30

## Context

A future repo will add a local-only MIMIC-IV adapter feeding the same feature service. MIMIC-IV
is relational CSV/Postgres data, not FHIR. Two integration strategies exist:

1. **FHIR as the interchange format**: the MIMIC adapter synthesizes FHIR bundles, which flow
   through the existing FHIR parser. Attractive on paper ("everything is FHIR"), but it forces
   the MIMIC repo to build a FHIR *encoder* — harder than a decoder, full of choices (which
   profile? which extension for race?) that this service would then have to parse back out.
   Round-tripping relational data through a document format loses precision and doubles the
   validation surface.
2. **A canonical intermediate representation (CIR)**: adapters emit the row models the store
   loads, directly. FHIR parsing becomes an implementation detail of one adapter.

## Decision

Adopt the CIR. `canonical/models.py` defines frozen pydantic v2 row models mirroring the
canonical tables 1:1, plus the unit of work
`PatientRecordSet(source, patient, encounters, conditions, observations, procedures,
medication_requests, immunizations, claim_diagnoses, codings, skipped, warnings)`.

`adapters/base.py` defines the boundary as a typed Protocol:

```python
class SourceAdapter(Protocol):
    source: ClassVar[str]

    def iter_patient_records(self) -> Iterator[PatientRecordSet]: ...
```

No runtime registry — that is ceremony for a system with one concrete adapter. `store/loader.py`
performs the transactional per-patient replace for ANY `PatientRecordSet`, regardless of origin.

The **normalization burden sits on the adapter by contract**: UTC timestamps plus source-local
dates with honest precision, normalized code systems, UCUM units. The contract is executable:
`fhir_features/testing/conformance.py` ships an `AdapterConformanceSuite` **inside the installed
wheel** (unique ids, resolvable FKs, valid precision enums, no events before birth, deterministic
across two runs, warnings carry codes/pointers but never values). The Synthea adapter passes it
in CI; the future MIMIC repo `pip install`s this package and must pass the identical suite.
MIMIC itself ships interface-only here: a stub with the correct signature, env-only config
validated to resolve outside the repo tree, and a docstring mapping plan. No MIMIC data, DDL, or
row counts are ever committed.

## Consequences

- The MIMIC repo writes plain relational-to-relational mapping code instead of a FHIR encoder —
  a large complexity transfer in the right direction.
- The CIR is a second schema to maintain alongside the DDL. They mirror 1:1 today; keeping them
  aligned is manual, guarded only by the loader's integration tests.
- Duplicated normalization risk: every adapter must independently get dates, code systems, and
  units right. The conformance suite checks the properties but cannot check MIMIC-specific
  mapping *correctness* — a wrong-but-well-formed mapping passes.
- Shipping the conformance suite in the wheel couples the two repos via a package version; a
  suite change here can break the MIMIC repo's CI. That is the intended pressure, but it makes
  suite changes semver-relevant.
- FHIR-specific richness (extensions, contained resources, narrative) is unavailable past the
  boundary by design; anything a feature needs must be promoted into the CIR explicitly.
