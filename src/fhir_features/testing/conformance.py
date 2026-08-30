"""The executable SourceAdapter contract (ADR-0003).

Any adapter — Synthea here, MIMIC-IV later in its own local-only context — must pass this
suite. Violations are returned as human-readable strings so a failing run reads like a review,
not a stack trace.
"""

from collections.abc import Iterable

from fhir_features.adapters.base import SourceAdapter
from fhir_features.canonical.models import PatientRecordSet

_VALID_PRECISIONS = {"second", "day", "month", "year"}
_KNOWN_SYSTEMS = {"SNOMED", "LOINC", "RXNORM", "CVX", "ICD10CM", "ICD9CM", "CPT", "UCUM"}


def _system_ok(system: str) -> bool:
    return system in _KNOWN_SYSTEMS or system.startswith("OTHER:")


class AdapterConformanceSuite:
    """Run the full contract against an adapter; ``run()`` returns violations (empty = pass)."""

    def __init__(self, adapter: SourceAdapter) -> None:
        self.adapter = adapter

    def run(self) -> list[str]:
        violations: list[str] = []
        first_pass = list(self.adapter.iter_patient_records())
        if not first_pass:
            return ["adapter yielded no patient records"]
        for record_set in first_pass:
            violations.extend(self._check_record_set(record_set))
        violations.extend(self._check_determinism(first_pass))
        return violations

    def _check_record_set(self, rs: PatientRecordSet) -> Iterable[str]:
        pid = rs.patient.patient_id
        prefix = f"[{rs.source}:{pid[:8]}…]"

        if rs.source != getattr(type(self.adapter), "source", rs.source):
            yield f"{prefix} record source {rs.source!r} != adapter.source"

        # Unique ids per record set.
        for name, ids in (
            ("encounter", [e.encounter_id for e in rs.encounters]),
            ("condition", [c.condition_id for c in rs.conditions]),
            ("observation", [o.observation_id for o in rs.observations]),
            ("procedure", [p.procedure_id for p in rs.procedures]),
            ("medication_request", [m.medication_request_id for m in rs.medication_requests]),
            ("immunization", [i.immunization_id for i in rs.immunizations]),
            ("claim_diagnosis", [(d.claim_id, d.diagnosis_sequence) for d in rs.claim_diagnoses]),
        ):
            if len(ids) != len(set(ids)):
                yield f"{prefix} duplicate {name} ids within one record set"

        # Every row must belong to the record set's patient.
        rows_with_patient = (
            [("encounter", e.patient_id) for e in rs.encounters]
            + [("condition", c.patient_id) for c in rs.conditions]
            + [("observation", o.patient_id) for o in rs.observations]
            + [("procedure", p.patient_id) for p in rs.procedures]
            + [("medication_request", m.patient_id) for m in rs.medication_requests]
            + [("immunization", i.patient_id) for i in rs.immunizations]
            + [("claim_diagnosis", d.patient_id) for d in rs.claim_diagnoses]
        )
        for name, row_pid in rows_with_patient:
            if row_pid != pid:
                yield f"{prefix} {name} row references foreign patient {row_pid[:8]}…"

        # Precision enums and normalized code systems.
        precisions = (
            [e.date_precision for e in rs.encounters]
            + [c.date_precision for c in rs.conditions]
            + [o.date_precision for o in rs.observations]
            + [p.date_precision for p in rs.procedures]
            + [m.date_precision for m in rs.medication_requests]
        )
        for precision in precisions:
            if precision not in _VALID_PRECISIONS:
                yield f"{prefix} invalid date_precision {precision!r}"

        systems = (
            [c.code_system for c in rs.conditions]
            + [o.code_system for o in rs.observations]
            + [p.code_system for p in rs.procedures]
            + [m.code_system for m in rs.medication_requests]
            + [i.code_system for i in rs.immunizations]
            + [d.diagnosis_code_system for d in rs.claim_diagnoses]
            + [c.code_system for c in rs.codings]
        )
        for system in systems:
            if not _system_ok(system):
                yield f"{prefix} unnormalized code system {system!r}"

        # No clinical events before birth (allow same-day: birth events are real).
        if rs.patient.birth_date is not None:
            birth = rs.patient.birth_date
            event_dates = (
                [("encounter", e.start_date) for e in rs.encounters]
                + [("condition", c.onset_date) for c in rs.conditions]
                + [("observation", o.effective_date) for o in rs.observations]
                + [("procedure", p.performed_date) for p in rs.procedures]
                + [("medication_request", m.authored_date) for m in rs.medication_requests]
                + [("immunization", i.occurrence_date) for i in rs.immunizations]
            )
            for name, event_date in event_dates:
                if event_date < birth:
                    yield f"{prefix} {name} dated {event_date} before birth {birth}"

        # Codings must reference rows that exist.
        condition_ids = {c.condition_id for c in rs.conditions}
        procedure_ids = {p.procedure_id for p in rs.procedures}
        for coding in rs.codings:
            pool = condition_ids if coding.resource_type == "Condition" else procedure_ids
            if coding.resource_id not in pool:
                yield f"{prefix} coding references missing {coding.resource_type} row"

        # Claim diagnoses must resolve to present conditions.
        for diag in rs.claim_diagnoses:
            if diag.resolved_condition_id not in condition_ids:
                yield f"{prefix} claim diagnosis references missing condition"

        # Warnings carry codes and pointers, never values.
        for issue in rs.warnings:
            if not issue.code or not issue.code.replace("_", "").isalnum():
                yield f"{prefix} warning with malformed code {issue.code!r}"
            if issue.json_pointer and not issue.json_pointer.startswith("/"):
                yield f"{prefix} warning pointer does not look like a JSON pointer"

    def _check_determinism(self, first_pass: list[PatientRecordSet]) -> Iterable[str]:
        second_pass = list(self.adapter.iter_patient_records())
        if len(second_pass) != len(first_pass):
            yield "adapter yielded a different record count on the second run"
            return
        for a, b in zip(first_pass, second_pass, strict=True):
            if a.model_dump() != b.model_dump():
                yield (
                    f"[{a.source}:{a.patient.patient_id[:8]}…] record set differs between runs "
                    "— adapters must be deterministic"
                )


def assert_conforms(adapter: SourceAdapter) -> None:
    """pytest-friendly wrapper: raise with the full violation list on any failure."""
    violations = AdapterConformanceSuite(adapter).run()
    if violations:
        raise AssertionError(
            "adapter conformance violations:\n" + "\n".join(f"  - {v}" for v in violations)
        )
