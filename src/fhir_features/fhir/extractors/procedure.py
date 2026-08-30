"""Procedure extractor.

Only ``status == "completed"`` procedures are stored (SPEC §5) — anything else is skipped
silently, without a ParseIssue. Every coding of ``Procedure.code`` is preserved as a
:class:`CodingRow` side row with the raw system URI intact.
"""

from collections.abc import Mapping
from typing import Any

from fhir_features.canonical.codes import Coding, normalize_system, pick_primary_coding
from fhir_features.canonical.dates import ParsedDateTime, parse_fhir_datetime
from fhir_features.canonical.models import CodingRow, ParseIssue, ProcedureRow
from fhir_features.fhir.bundle import RefMap, resolve_reference

_PREFERRED_SYSTEMS = ("SNOMED", "CPT")


def _reference_str(field: Any) -> str | None:
    """Pull the ``reference`` string out of a FHIR Reference element, if any."""
    if isinstance(field, Mapping):
        ref = field.get("reference")
        if isinstance(ref, str) and ref:
            return ref
    return None


def _code_codings(resource: Mapping[str, Any]) -> list[Coding]:
    """Read ``code.coding`` into typed Coding dicts, dropping non-object entries."""
    concept = resource.get("code")
    if not isinstance(concept, Mapping):
        return []
    raw = concept.get("coding")
    if not isinstance(raw, list):
        return []
    codings: list[Coding] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        coding: Coding = {}
        system = item.get("system")
        if isinstance(system, str):
            coding["system"] = system
        code = item.get("code")
        if isinstance(code, str):
            coding["code"] = code
        display = item.get("display")
        if isinstance(display, str):
            coding["display"] = display
        codings.append(coding)
    return codings


def _performed_start(
    resource: Mapping[str, Any], pointer: str
) -> tuple[ParsedDateTime | None, str]:
    """Resolve the performed start: ``performedDateTime`` first, then ``performedPeriod.start``.

    Returns the parsed value plus the JSON pointer of the field it came from; on failure the
    pointer names the most specific field that was present-but-unparseable (or the canonical
    ``performedDateTime`` location when neither field was present).
    """
    raw_dt = resource.get("performedDateTime")
    if raw_dt is not None and (parsed := parse_fhir_datetime(str(raw_dt))):
        return parsed, f"{pointer}/performedDateTime"
    period = resource.get("performedPeriod")
    raw_start = period.get("start") if isinstance(period, Mapping) else None
    if raw_start is not None and (parsed := parse_fhir_datetime(str(raw_start))):
        return parsed, f"{pointer}/performedPeriod/start"
    if raw_start is not None:
        return None, f"{pointer}/performedPeriod/start"
    return None, f"{pointer}/performedDateTime"


def extract_procedure(
    resource: Mapping[str, Any], refmap: RefMap, pointer: str
) -> tuple[ProcedureRow | None, list[CodingRow], list[ParseIssue]]:
    # Out-of-scope statuses (not-done, in-progress, ...) are filtered, not flagged.
    if resource.get("status") != "completed":
        return None, [], []

    procedure_id = resource.get("id")
    if not isinstance(procedure_id, str) or not procedure_id:
        return None, [], [ParseIssue(code="procedure_missing_id", json_pointer=f"{pointer}/id")]

    codings = _code_codings(resource)
    primary = pick_primary_coding(codings, prefer=_PREFERRED_SYSTEMS)
    if primary is None:
        return (
            None,
            [],
            [ParseIssue(code="procedure_missing_code", json_pointer=f"{pointer}/code")],
        )

    subject = resolve_reference(_reference_str(resource.get("subject")), refmap)
    if subject is None or subject[0] != "Patient":
        return (
            None,
            [],
            [
                ParseIssue(
                    code="dangling_subject_reference",
                    json_pointer=f"{pointer}/subject/reference",
                )
            ],
        )
    patient_id = subject[1]

    performed, performed_pointer = _performed_start(resource, pointer)
    if performed is None:
        return (
            None,
            [],
            [ParseIssue(code="procedure_missing_performed", json_pointer=performed_pointer)],
        )

    issues: list[ParseIssue] = []

    encounter_id: str | None = None
    if encounter_ref := _reference_str(resource.get("encounter")):
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

    performed_end_date = None
    period = resource.get("performedPeriod")
    if isinstance(period, Mapping) and (raw_end := period.get("end")) is not None:
        if parsed_end := parse_fhir_datetime(str(raw_end)):
            performed_end_date = parsed_end.local_date
        else:
            issues.append(
                ParseIssue(
                    code="unparseable_performed_end",
                    json_pointer=f"{pointer}/performedPeriod/end",
                )
            )

    coding_rows = [
        CodingRow(
            resource_type="Procedure",
            resource_id=procedure_id,
            coding_seq=seq,
            code=coding["code"],
            code_system_uri=coding.get("system"),
            code_system=normalize_system(coding.get("system")),
            display=coding.get("display"),
        )
        for seq, coding in enumerate(c for c in codings if c.get("code"))
    ]

    return (
        ProcedureRow(
            procedure_id=procedure_id,
            patient_id=patient_id,
            encounter_id=encounter_id,
            code=primary["code"],
            code_system=normalize_system(primary.get("system")),
            code_display=primary.get("display"),
            performed_date=performed.local_date,
            performed_end_date=performed_end_date,
            date_precision=performed.precision,
            status="completed",
        ),
        coding_rows,
        issues,
    )
