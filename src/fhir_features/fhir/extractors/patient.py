"""Patient extractor — the reference pattern for all extractors.

Minimum-necessary by construction: name, telecom, identifiers, photo, and contact are never
read, so they cannot leak into logs, errors, or responses.
"""

from collections.abc import Mapping
from typing import Any, Literal, cast

from fhir_features.canonical.dates import parse_fhir_datetime
from fhir_features.canonical.models import ParseIssue, PatientRow

_RACE_EXT = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race"
_ETHNICITY_EXT = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-ethnicity"
_SEXES = ("male", "female", "other", "unknown")


def _us_core_text(resource: Mapping[str, Any], url: str) -> str | None:
    """Pull the ``text`` sub-extension value of a US Core race/ethnicity extension."""
    for ext in resource.get("extension") or []:
        if isinstance(ext, Mapping) and ext.get("url") == url:
            for sub in ext.get("extension") or []:
                if isinstance(sub, Mapping) and sub.get("url") == "text":
                    value = sub.get("valueString")
                    return value if isinstance(value, str) else None
    return None


def extract_patient(
    resource: Mapping[str, Any], pointer: str
) -> tuple[PatientRow | None, list[ParseIssue]]:
    issues: list[ParseIssue] = []

    patient_id = resource.get("id")
    if not isinstance(patient_id, str) or not patient_id:
        return None, [ParseIssue(code="patient_missing_id", json_pointer=f"{pointer}/id")]

    birth_date = None
    if raw_birth := resource.get("birthDate"):
        if parsed := parse_fhir_datetime(str(raw_birth)):
            birth_date = parsed.local_date
        else:
            issues.append(
                ParseIssue(code="unparseable_birth_date", json_pointer=f"{pointer}/birthDate")
            )

    death_date = None
    if raw_death := resource.get("deceasedDateTime"):
        if parsed := parse_fhir_datetime(str(raw_death)):
            death_date = parsed.local_date
        else:
            issues.append(
                ParseIssue(
                    code="unparseable_death_date", json_pointer=f"{pointer}/deceasedDateTime"
                )
            )

    raw_sex = resource.get("gender")
    sex: Literal["male", "female", "other", "unknown"] = (
        cast(Literal["male", "female", "other", "unknown"], raw_sex)
        if raw_sex in _SEXES
        else "unknown"
    )

    address = (resource.get("address") or [{}])[0]
    if not isinstance(address, Mapping):
        address = {}

    def _opt_str(value: Any) -> str | None:
        return value if isinstance(value, str) and value else None

    return (
        PatientRow(
            patient_id=patient_id,
            birth_date=birth_date,
            death_date=death_date,
            sex=sex,
            race=_us_core_text(resource, _RACE_EXT),
            ethnicity=_us_core_text(resource, _ETHNICITY_EXT),
            city=_opt_str(address.get("city")),
            state=_opt_str(address.get("state")),
            postal_code=_opt_str(address.get("postalCode")),
        ),
        issues,
    )
