"""MedicationRequest extractor.

Only ``authoredOn`` feeds feature logic (statin/med recency windows — SPEC §5); ``status`` and
``intent`` are stored verbatim for display and are never used in features. Synthea carries no
reliable stop dates, so the authored date is the honest signal (SPEC §10).
"""

from collections.abc import Mapping
from typing import Any, cast

from fhir_features.canonical.codes import Coding, normalize_system, pick_primary_coding
from fhir_features.canonical.dates import parse_fhir_datetime
from fhir_features.canonical.models import MedicationRequestRow, ParseIssue
from fhir_features.fhir.bundle import RefMap, resolve_reference


def _codings(concept: Any) -> list[Coding]:
    """Collect the Mapping entries of a CodeableConcept's ``coding`` list (untrusted input)."""
    if not isinstance(concept, Mapping):
        return []
    codings = concept.get("coding")
    if not isinstance(codings, list):
        return []
    return [cast(Coding, coding) for coding in codings if isinstance(coding, Mapping)]


def _reference(field: Any) -> str | None:
    """Pull the ``reference`` string out of a FHIR Reference element, if usable."""
    if isinstance(field, Mapping):
        ref = field.get("reference")
        if isinstance(ref, str) and ref:
            return ref
    return None


def _opt_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def extract_medication_request(
    resource: Mapping[str, Any], refmap: RefMap, pointer: str
) -> tuple[MedicationRequestRow | None, list[ParseIssue]]:
    issues: list[ParseIssue] = []

    request_id = resource.get("id")
    if not isinstance(request_id, str) or not request_id:
        return None, [ParseIssue(code="medication_missing_id", json_pointer=f"{pointer}/id")]

    coding = pick_primary_coding(
        _codings(resource.get("medicationCodeableConcept")), prefer=("RXNORM",)
    )
    code = coding.get("code") if coding else None
    if coding is None or not isinstance(code, str) or not code:
        return None, [
            ParseIssue(
                code="medication_missing_code",
                json_pointer=f"{pointer}/medicationCodeableConcept",
            )
        ]

    parsed = None
    if raw_authored := resource.get("authoredOn"):
        parsed = parse_fhir_datetime(str(raw_authored))
    if parsed is None:
        return None, [
            ParseIssue(code="medication_missing_authored", json_pointer=f"{pointer}/authoredOn")
        ]

    subject = resolve_reference(_reference(resource.get("subject")), refmap)
    if subject is None or subject[0] != "Patient":
        return None, [
            ParseIssue(
                code="dangling_subject_reference", json_pointer=f"{pointer}/subject/reference"
            )
        ]

    encounter_id = None
    if encounter_ref := _reference(resource.get("encounter")):
        resolved = resolve_reference(encounter_ref, refmap)
        if resolved is not None and resolved[0] == "Encounter":
            encounter_id = resolved[1]
        else:
            issues.append(
                ParseIssue(
                    code="dangling_encounter_reference",
                    json_pointer=f"{pointer}/encounter/reference",
                )
            )

    return (
        MedicationRequestRow(
            medication_request_id=request_id,
            patient_id=subject[1],
            encounter_id=encounter_id,
            code=code,
            code_system=normalize_system(_opt_str(coding.get("system"))),
            code_display=_opt_str(coding.get("display")),
            authored_date=parsed.local_date,
            date_precision=parsed.precision,
            status=_opt_str(resource.get("status")),
            intent=_opt_str(resource.get("intent")),
        ),
        issues,
    )
