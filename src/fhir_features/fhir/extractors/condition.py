"""Condition extractor.

Clinical/verification statuses are stored for display context only — feature logic is strictly
date-derived (the leakage rule, SPEC §5). Every coding with a code is preserved in the codings
side table with its raw system URI; when the row itself is dropped its codings are dropped too,
so the side table never holds orphan foreign keys.
"""

from collections.abc import Mapping
from typing import Any, cast

from fhir_features.canonical.codes import Coding, normalize_system, pick_primary_coding
from fhir_features.canonical.dates import ParsedDateTime, parse_fhir_datetime
from fhir_features.canonical.models import CodingRow, ConditionRow, ParseIssue
from fhir_features.fhir.bundle import RefMap, resolve_reference

_PREFERRED_SYSTEMS = ("SNOMED", "ICD10CM", "ICD9CM")


def _codings_of(element: Any) -> list[Coding]:
    """Collect the well-shaped entries of a CodeableConcept's ``coding`` list (untrusted input)."""
    if not isinstance(element, Mapping):
        return []
    raw = element.get("coding")
    if not isinstance(raw, list):
        return []
    return [cast(Coding, coding) for coding in raw if isinstance(coding, Mapping)]


def _first_coding_code(element: Any) -> str | None:
    """Pull ``coding[0].code`` of a CodeableConcept (the clinical/verification status shape)."""
    codings = _codings_of(element)
    if not codings:
        return None
    return _opt_str(codings[0].get("code"))


def _opt_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def extract_condition(
    resource: Mapping[str, Any], refmap: RefMap, pointer: str
) -> tuple[ConditionRow | None, list[CodingRow], list[ParseIssue]]:
    issues: list[ParseIssue] = []

    condition_id = resource.get("id")
    if not isinstance(condition_id, str) or not condition_id:
        return None, [], [ParseIssue(code="condition_missing_id", json_pointer=f"{pointer}/id")]

    subject = resource.get("subject")
    subject_ref = subject.get("reference") if isinstance(subject, Mapping) else None
    resolved_subject = resolve_reference(
        subject_ref if isinstance(subject_ref, str) else None, refmap
    )
    if resolved_subject is None or resolved_subject[0] != "Patient":
        issues.append(
            ParseIssue(
                code="dangling_subject_reference", json_pointer=f"{pointer}/subject/reference"
            )
        )
        return None, [], issues
    patient_id = resolved_subject[1]

    codings = _codings_of(resource.get("code"))
    primary = pick_primary_coding(codings, prefer=_PREFERRED_SYSTEMS)
    primary_code = _opt_str(primary.get("code")) if primary else None
    if primary is None or primary_code is None:
        issues.append(ParseIssue(code="condition_missing_code", json_pointer=f"{pointer}/code"))
        return None, [], issues

    coding_rows: list[CodingRow] = []
    for seq, coding in enumerate(codings):
        code = _opt_str(coding.get("code"))
        if code is None:
            continue
        raw_system = _opt_str(coding.get("system"))
        coding_rows.append(
            CodingRow(
                resource_type="Condition",
                resource_id=condition_id,
                coding_seq=seq,
                code=code,
                code_system_uri=raw_system,
                code_system=normalize_system(raw_system),
                display=_opt_str(coding.get("display")),
            )
        )

    onset_parsed: ParsedDateTime | None = None
    if raw_onset := resource.get("onsetDateTime"):
        onset_parsed = parse_fhir_datetime(str(raw_onset))
        if onset_parsed is None:
            issues.append(
                ParseIssue(code="unparseable_onset_date", json_pointer=f"{pointer}/onsetDateTime")
            )

    recorded_parsed: ParsedDateTime | None = None
    if raw_recorded := resource.get("recordedDate"):
        recorded_parsed = parse_fhir_datetime(str(raw_recorded))
        if recorded_parsed is None:
            issues.append(
                ParseIssue(code="unparseable_recorded_date", json_pointer=f"{pointer}/recordedDate")
            )

    if onset_parsed is not None:
        onset_source = onset_parsed
    elif recorded_parsed is not None:
        # Optimistic imputation, kept visible: the warning marks every imputed onset.
        onset_source = recorded_parsed
        issues.append(
            ParseIssue(code="onset_imputed_from_recorded", json_pointer=f"{pointer}/recordedDate")
        )
    else:
        issues.append(
            ParseIssue(code="condition_missing_onset", json_pointer=f"{pointer}/onsetDateTime")
        )
        return None, [], issues

    abatement_date = None
    if raw_abatement := resource.get("abatementDateTime"):
        if parsed := parse_fhir_datetime(str(raw_abatement)):
            abatement_date = parsed.local_date
        else:
            issues.append(
                ParseIssue(
                    code="unparseable_abatement_date",
                    json_pointer=f"{pointer}/abatementDateTime",
                )
            )

    encounter_id = None
    if raw_encounter := resource.get("encounter"):
        ref = raw_encounter.get("reference") if isinstance(raw_encounter, Mapping) else None
        resolved = resolve_reference(ref if isinstance(ref, str) else None, refmap)
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
        ConditionRow(
            condition_id=condition_id,
            patient_id=patient_id,
            encounter_id=encounter_id,
            code=primary_code,
            code_system=normalize_system(_opt_str(primary.get("system"))),
            code_display=_opt_str(primary.get("display")),
            clinical_status=_first_coding_code(resource.get("clinicalStatus")),
            verification_status=_first_coding_code(resource.get("verificationStatus")),
            onset_date=onset_source.local_date,
            abatement_date=abatement_date,
            recorded_date=recorded_parsed.local_date if recorded_parsed else None,
            date_precision=onset_source.precision,
        ),
        coding_rows,
        issues,
    )
