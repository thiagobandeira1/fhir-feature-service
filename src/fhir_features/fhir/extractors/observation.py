"""Observation extractor — value[x] mapping plus component-panel flattening.

``Observation.component`` entries (systolic/diastolic inside a blood-pressure panel) become
child rows whose id is ``'<parent_id>#<component_code>'`` — keyed by CODE, never by position,
so re-ingesting the same bundle always yields identical child ids (see SPEC §5). Only statuses
``final``/``amended``/``corrected`` are stored; anything else is filtered silently by design.
"""

from collections.abc import Mapping
from typing import Any

from fhir_features.canonical.codes import Coding, normalize_system, pick_primary_coding
from fhir_features.canonical.dates import ParsedDateTime, parse_fhir_datetime
from fhir_features.canonical.models import ObservationRow, ParseIssue
from fhir_features.fhir.bundle import RefMap, resolve_reference

_STORED_STATUSES = ("final", "amended", "corrected")
_PREFER = ("LOINC", "SNOMED")


def _opt_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _codings(concept: Any) -> list[Coding]:
    """Safely read the ``coding`` list of an untrusted CodeableConcept element."""
    result: list[Coding] = []
    if not isinstance(concept, Mapping):
        return result
    raw_codings = concept.get("coding")
    if not isinstance(raw_codings, list):
        return result
    for raw in raw_codings:
        if not isinstance(raw, Mapping):
            continue
        coding = Coding()
        if system := _opt_str(raw.get("system")):
            coding["system"] = system
        if code := _opt_str(raw.get("code")):
            coding["code"] = code
        if display := _opt_str(raw.get("display")):
            coding["display"] = display
        result.append(coding)
    return result


def _quantity_fields(quantity: Any) -> tuple[float | None, str | None]:
    """Read ``(value_num, value_unit)`` from an untrusted Quantity; the UCUM ``code`` wins
    over the free-text ``unit``."""
    if not isinstance(quantity, Mapping):
        return None, None
    raw_value = quantity.get("value")
    value_num = (
        float(raw_value)
        if isinstance(raw_value, int | float) and not isinstance(raw_value, bool)
        else None
    )
    return value_num, _opt_str(quantity.get("code")) or _opt_str(quantity.get("unit"))


def _category_code(resource: Mapping[str, Any]) -> str | None:
    """``category[0].coding[0].code`` — None when any hop is absent or malformed."""
    categories = resource.get("category")
    if not isinstance(categories, list) or not categories:
        return None
    codings = _codings(categories[0])
    return codings[0].get("code") if codings else None


def _parse_effective(
    resource: Mapping[str, Any], pointer: str, issues: list[ParseIssue]
) -> ParsedDateTime | None:
    """``effectiveDateTime``, else ``issued`` (recording the imputation), else None (drop)."""
    raw_effective = resource.get("effectiveDateTime")
    if raw_effective and (parsed := parse_fhir_datetime(str(raw_effective))):
        return parsed
    raw_issued = resource.get("issued")
    if raw_issued and (parsed := parse_fhir_datetime(str(raw_issued))):
        issues.append(
            ParseIssue(
                code="effective_imputed_from_issued",
                json_pointer=f"{pointer}/effectiveDateTime",
            )
        )
        return parsed
    return None


def extract_observation(
    resource: Mapping[str, Any], refmap: RefMap, pointer: str
) -> tuple[list[ObservationRow], list[ParseIssue]]:
    # Status filter comes before everything else: non-stored statuses are not an error.
    status = resource.get("status")
    if not isinstance(status, str) or status not in _STORED_STATUSES:
        return [], []

    issues: list[ParseIssue] = []

    observation_id = resource.get("id")
    if not isinstance(observation_id, str) or not observation_id:
        return [], [ParseIssue(code="observation_missing_id", json_pointer=f"{pointer}/id")]

    subject = resource.get("subject")
    subject_ref = subject.get("reference") if isinstance(subject, Mapping) else None
    resolved = resolve_reference(_opt_str(subject_ref), refmap)
    if resolved is None or resolved[0] != "Patient":
        issues.append(
            ParseIssue(
                code="dangling_subject_reference", json_pointer=f"{pointer}/subject/reference"
            )
        )
        return [], issues
    patient_id = resolved[1]

    primary = pick_primary_coding(_codings(resource.get("code")), prefer=_PREFER)
    if primary is None:
        issues.append(ParseIssue(code="observation_missing_code", json_pointer=f"{pointer}/code"))
        return [], issues

    effective = _parse_effective(resource, pointer, issues)
    if effective is None:
        issues.append(
            ParseIssue(
                code="observation_missing_effective",
                json_pointer=f"{pointer}/effectiveDateTime",
            )
        )
        return [], issues

    encounter_id: str | None = None
    encounter = resource.get("encounter")
    if isinstance(encounter, Mapping) and encounter.get("reference") is not None:
        resolved_enc = resolve_reference(_opt_str(encounter.get("reference")), refmap)
        if resolved_enc is not None and resolved_enc[0] == "Encounter":
            encounter_id = resolved_enc[1]
        else:
            issues.append(
                ParseIssue(
                    code="dangling_encounter_reference",
                    json_pointer=f"{pointer}/encounter/reference",
                )
            )

    category = _category_code(resource)
    value_num, value_unit = _quantity_fields(resource.get("valueQuantity"))
    value_code: str | None = None
    value_code_system: str | None = None
    value_codings = _codings(resource.get("valueCodeableConcept"))
    if value_codings and (coded := value_codings[0].get("code")):
        value_code = coded
        value_code_system = normalize_system(value_codings[0].get("system"))
    value_text = _opt_str(resource.get("valueString"))

    rows = [
        ObservationRow(
            observation_id=observation_id,
            patient_id=patient_id,
            encounter_id=encounter_id,
            code=primary["code"],
            code_system=normalize_system(primary.get("system")),
            code_display=primary.get("display"),
            category=category,
            effective_ts=effective.utc_ts,
            effective_date=effective.local_date,
            date_precision=effective.precision,
            value_num=value_num,
            value_unit=value_unit,
            value_code=value_code,
            value_code_system=value_code_system,
            value_text=value_text,
            status=status,
        )
    ]

    seen_component_codes: set[str] = set()
    for comp_index, component in enumerate(resource.get("component") or []):
        if not isinstance(component, Mapping):
            continue
        comp_coding = pick_primary_coding(_codings(component.get("code")), prefer=_PREFER)
        quantity = component.get("valueQuantity")
        if comp_coding is None or not isinstance(quantity, Mapping):
            continue  # a component without a code or a quantity value carries nothing storable
        if comp_coding["code"] in seen_component_codes:
            # Repeated component codes are legal FHIR; the code-keyed child id cannot hold two.
            # Keep the first, surface the drop — never let a PK collision kill the bundle.
            issues.append(
                ParseIssue(
                    code="duplicate_component_code",
                    json_pointer=f"{pointer}/component/{comp_index}",
                )
            )
            continue
        seen_component_codes.add(comp_coding["code"])
        comp_num, comp_unit = _quantity_fields(quantity)
        rows.append(
            ObservationRow(
                observation_id=f"{observation_id}#{comp_coding['code']}",
                parent_observation_id=observation_id,
                patient_id=patient_id,
                encounter_id=encounter_id,
                code=comp_coding["code"],
                code_system=normalize_system(comp_coding.get("system")),
                code_display=comp_coding.get("display"),
                category=category,
                effective_ts=effective.utc_ts,
                effective_date=effective.local_date,
                date_precision=effective.precision,
                value_num=comp_num,
                value_unit=comp_unit,
                status=status,
            )
        )

    return rows, issues
