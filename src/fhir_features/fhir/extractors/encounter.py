"""Encounter extractor.

R4 ``Encounter.class`` is a single Coding element (not a CodeableConcept); its code runs through
the dual ActCode/Synthea-lowercase mapping so ``IMP`` and ``inpatient`` land on the same enum
value, with ``OTHER`` guaranteeing counts still reconcile. ``period.start`` is the required event
date — every encounter window feature keys off it, so a missing or garbage start drops the row.
"""

from collections.abc import Mapping
from typing import Any

from fhir_features.canonical.codes import (
    Coding,
    normalize_encounter_class,
    normalize_system,
    pick_primary_coding,
)
from fhir_features.canonical.dates import parse_fhir_datetime
from fhir_features.canonical.models import EncounterRow, ParseIssue
from fhir_features.fhir.bundle import RefMap, resolve_reference


def _codeable_concept_codings(concept: Any) -> list[Coding]:
    """Collect the well-formed codings of an untrusted CodeableConcept-shaped value."""
    if not isinstance(concept, Mapping):
        return []
    raw_codings = concept.get("coding")
    if not isinstance(raw_codings, list):
        return []
    codings: list[Coding] = []
    for raw in raw_codings:
        if not isinstance(raw, Mapping):
            continue
        coding: Coding = {}
        system = raw.get("system")
        code = raw.get("code")
        display = raw.get("display")
        if isinstance(system, str):
            coding["system"] = system
        if isinstance(code, str):
            coding["code"] = code
        if isinstance(display, str):
            coding["display"] = display
        codings.append(coding)
    return codings


def extract_encounter(
    resource: Mapping[str, Any], refmap: RefMap, pointer: str
) -> tuple[EncounterRow | None, list[ParseIssue]]:
    issues: list[ParseIssue] = []

    encounter_id = resource.get("id")
    if not isinstance(encounter_id, str) or not encounter_id:
        return None, [ParseIssue(code="encounter_missing_id", json_pointer=f"{pointer}/id")]

    subject = resource.get("subject")
    ref = subject.get("reference") if isinstance(subject, Mapping) else None
    resolved = resolve_reference(ref if isinstance(ref, str) else None, refmap)
    if resolved is None or resolved[0] != "Patient":
        return None, [
            ParseIssue(
                code="dangling_subject_reference", json_pointer=f"{pointer}/subject/reference"
            )
        ]
    patient_id = resolved[1]

    period = resource.get("period")
    if not isinstance(period, Mapping):
        period = {}
    start = None
    if raw_start := period.get("start"):
        start = parse_fhir_datetime(str(raw_start))
    if start is None:
        return None, [
            ParseIssue(code="encounter_missing_start", json_pointer=f"{pointer}/period/start")
        ]

    end_ts = None
    if raw_end := period.get("end"):
        if parsed_end := parse_fhir_datetime(str(raw_end)):
            end_ts = parsed_end.utc_ts
        else:
            issues.append(
                ParseIssue(code="unparseable_end_date", json_pointer=f"{pointer}/period/end")
            )

    raw_class = resource.get("class")
    class_code = raw_class.get("code") if isinstance(raw_class, Mapping) else None
    encounter_class = normalize_encounter_class(class_code if isinstance(class_code, str) else None)

    raw_types = resource.get("type")
    first_type = raw_types[0] if isinstance(raw_types, list) and raw_types else None
    picked = pick_primary_coding(_codeable_concept_codings(first_type), prefer=("SNOMED",))

    return (
        EncounterRow(
            encounter_id=encounter_id,
            patient_id=patient_id,
            encounter_class=encounter_class,
            type_code=picked.get("code") if picked else None,
            type_system=normalize_system(picked.get("system")) if picked else None,
            type_display=picked.get("display") if picked else None,
            start_ts=start.utc_ts,
            end_ts=end_ts,
            start_date=start.local_date,
            date_precision=start.precision,
        ),
        issues,
    )
