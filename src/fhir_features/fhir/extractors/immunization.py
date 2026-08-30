"""Immunization extractor — CVX-coded completed immunizations.

Only ``status == "completed"`` rows carry signal for the flu-vaccine feature; every other
status is dropped silently (no issue — absence is expected, not a parse problem). The patient
link is ``Immunization.patient``, not ``subject``.
"""

from collections.abc import Mapping
from typing import Any

from fhir_features.canonical.codes import Coding, normalize_system, pick_primary_coding
from fhir_features.canonical.dates import parse_fhir_datetime
from fhir_features.canonical.models import ImmunizationRow, ParseIssue
from fhir_features.fhir.bundle import RefMap, resolve_reference


def _codings(concept: Any) -> list[Coding]:
    """Pull the well-formed codings out of an untrusted CodeableConcept element."""
    if not isinstance(concept, Mapping):
        return []
    codings: list[Coding] = []
    for raw in concept.get("coding") or []:
        if not isinstance(raw, Mapping):
            continue
        coding: Coding = {}
        if isinstance(raw.get("system"), str):
            coding["system"] = raw["system"]
        if isinstance(raw.get("code"), str):
            coding["code"] = raw["code"]
        if isinstance(raw.get("display"), str):
            coding["display"] = raw["display"]
        codings.append(coding)
    return codings


def _reference(field: Any) -> str | None:
    """Pull the ``reference`` string out of an untrusted Reference element."""
    if isinstance(field, Mapping):
        ref = field.get("reference")
        if isinstance(ref, str):
            return ref
    return None


def extract_immunization(
    resource: Mapping[str, Any], refmap: RefMap, pointer: str
) -> tuple[ImmunizationRow | None, list[ParseIssue]]:
    if resource.get("status") != "completed":
        return None, []

    immunization_id = resource.get("id")
    if not isinstance(immunization_id, str) or not immunization_id:
        return None, [ParseIssue(code="immunization_missing_id", json_pointer=f"{pointer}/id")]

    resolved = resolve_reference(_reference(resource.get("patient")), refmap)
    if resolved is None or resolved[0] != "Patient":
        return None, [
            ParseIssue(code="dangling_subject_reference", json_pointer=f"{pointer}/patient")
        ]

    picked = pick_primary_coding(_codings(resource.get("vaccineCode")), prefer=("CVX",))
    if picked is None or not picked.get("code"):
        return None, [
            ParseIssue(code="immunization_missing_code", json_pointer=f"{pointer}/vaccineCode")
        ]

    parsed = None
    if raw_occurrence := resource.get("occurrenceDateTime"):
        parsed = parse_fhir_datetime(str(raw_occurrence))
    if parsed is None:
        return None, [
            ParseIssue(
                code="immunization_missing_occurrence",
                json_pointer=f"{pointer}/occurrenceDateTime",
            )
        ]

    return (
        ImmunizationRow(
            immunization_id=immunization_id,
            patient_id=resolved[1],
            code=picked["code"],
            code_system=normalize_system(picked.get("system")),
            code_display=picked.get("display"),
            occurrence_date=parsed.local_date,
        ),
        [],
    )
