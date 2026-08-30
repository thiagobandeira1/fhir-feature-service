"""Claim extractor — flattens ``Claim.diagnosis[]`` into claims-shaped diagnosis rows.

Only ``use == "claim"`` resources count (preauthorization/predetermination skip silently).
Each ``diagnosisReference`` must resolve to an in-bundle Condition already extracted into
``conditions_by_id``; the row copies that Condition's primary coding so P4 gets code +
service date + sequence without a join. ``billablePeriod.start`` is the service-date proxy
for HCC lookback. Claims with no ``diagnosis[]`` (Synthea emits many such pharmacy claims)
produce no rows and no issues.
"""

from collections.abc import Mapping
from datetime import date
from typing import Any

from fhir_features.canonical.dates import parse_fhir_datetime
from fhir_features.canonical.models import ClaimDiagnosisRow, ConditionRow, ParseIssue
from fhir_features.fhir.bundle import RefMap, resolve_reference


def _claim_type(resource: Mapping[str, Any]) -> str | None:
    """Read ``type.coding[0].code`` verbatim (institutional | professional | pharmacy | ...)."""
    concept = resource.get("type")
    if not isinstance(concept, Mapping):
        return None
    codings = concept.get("coding")
    if not isinstance(codings, list) or not codings or not isinstance(codings[0], Mapping):
        return None
    code = codings[0].get("code")
    return code if isinstance(code, str) and code else None


def _reference(field: Any) -> str | None:
    """Pull the ``reference`` string out of an untrusted Reference element."""
    if isinstance(field, Mapping):
        ref = field.get("reference")
        if isinstance(ref, str):
            return ref
    return None


def extract_claim_diagnoses(
    resource: Mapping[str, Any],
    refmap: RefMap,
    conditions_by_id: Mapping[str, ConditionRow],
    pointer: str,
) -> tuple[list[ClaimDiagnosisRow], list[ParseIssue]]:
    if resource.get("use") != "claim":
        return [], []

    claim_id = resource.get("id")
    if not isinstance(claim_id, str) or not claim_id:
        return [], [ParseIssue(code="claim_missing_id", json_pointer=f"{pointer}/id")]

    diagnoses = resource.get("diagnosis")
    if not isinstance(diagnoses, list) or not diagnoses:
        return [], []

    resolved = resolve_reference(_reference(resource.get("patient")), refmap)
    if resolved is None or resolved[0] != "Patient":
        return [], [
            ParseIssue(code="dangling_subject_reference", json_pointer=f"{pointer}/patient")
        ]
    patient_id = resolved[1]

    issues: list[ParseIssue] = []
    claim_type = _claim_type(resource)

    raw_period = resource.get("billablePeriod")
    period: Mapping[str, Any] = raw_period if isinstance(raw_period, Mapping) else {}
    billable: dict[str, date | None] = {"start": None, "end": None}
    for field in ("start", "end"):
        if raw := period.get(field):
            if parsed := parse_fhir_datetime(str(raw)):
                billable[field] = parsed.local_date
            else:
                issues.append(
                    ParseIssue(
                        code="unparseable_billable_period",
                        json_pointer=f"{pointer}/billablePeriod/{field}",
                    )
                )

    rows: list[ClaimDiagnosisRow] = []
    for i, entry in enumerate(diagnoses):
        if not isinstance(entry, Mapping) or "diagnosisReference" not in entry:
            # diagnosisCodeableConcept-only entries are out of scope for v1 — skip silently.
            continue
        dx_resolved = resolve_reference(_reference(entry.get("diagnosisReference")), refmap)
        condition = (
            conditions_by_id.get(dx_resolved[1])
            if dx_resolved is not None and dx_resolved[0] == "Condition"
            else None
        )
        if condition is None:
            issues.append(
                ParseIssue(
                    code="dangling_diagnosis_reference",
                    json_pointer=f"{pointer}/diagnosis/{i}/diagnosisReference",
                )
            )
            continue
        sequence = entry.get("sequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool):
            issues.append(
                ParseIssue(
                    code="diagnosis_missing_sequence",
                    json_pointer=f"{pointer}/diagnosis/{i}/sequence",
                )
            )
            continue
        rows.append(
            ClaimDiagnosisRow(
                claim_id=claim_id,
                diagnosis_sequence=sequence,
                patient_id=patient_id,
                claim_type=claim_type,
                billable_period_start=billable["start"],
                billable_period_end=billable["end"],
                diagnosis_code=condition.code,
                diagnosis_code_system=condition.code_system,
                diagnosis_display=condition.code_display,
                resolved_condition_id=condition.condition_id,
            )
        )
    return rows, issues
