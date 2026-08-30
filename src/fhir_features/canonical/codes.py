"""Code-system normalization and coding selection.

Raw system URIs are always preserved in ``resource_codings``; the normalized short names below
exist so SQL and value sets can join on stable tokens (see ADR-0007).
"""

from typing import Literal, TypedDict

EncounterClass = Literal["AMB", "IMP", "EMER", "WELLNESS", "URGENT", "HH", "VR", "OTHER"]

SYSTEM_URI_MAP: dict[str, str] = {
    "http://snomed.info/sct": "SNOMED",
    "http://loinc.org": "LOINC",
    "http://www.nlm.nih.gov/research/umls/rxnorm": "RXNORM",
    "http://hl7.org/fhir/sid/cvx": "CVX",
    "http://hl7.org/fhir/sid/icd-10-cm": "ICD10CM",
    "http://hl7.org/fhir/sid/icd-9-cm": "ICD9CM",
    "http://www.ama-assn.org/go/cpt": "CPT",
    "http://unitsofmeasure.org": "UCUM",
}

# Covers BOTH HL7 v3-ActCode tokens and the lowercase strings Synthea emits
# (mapping derived from actual fixture data; OTHER guarantees counts still reconcile).
_ENCOUNTER_CLASS_MAP: dict[str, EncounterClass] = {
    "amb": "AMB",
    "ambulatory": "AMB",
    "outpatient": "AMB",
    "imp": "IMP",
    "inpatient": "IMP",
    "acute": "IMP",
    "emer": "EMER",
    "emergency": "EMER",
    "wellness": "WELLNESS",
    "urgent": "URGENT",
    "urgentcare": "URGENT",
    "hh": "HH",
    "home": "HH",
    "homehealth": "HH",
    "vr": "VR",
    "virtual": "VR",
}


class Coding(TypedDict, total=False):
    """The subset of a FHIR ``Coding`` element this service reads."""

    system: str
    code: str
    display: str


def normalize_system(uri: str | None) -> str:
    """Map a code-system URI to its short name; unmapped URIs become ``OTHER:<uri>``."""
    if not uri:
        return "OTHER:"
    return SYSTEM_URI_MAP.get(uri, f"OTHER:{uri}")


def normalize_encounter_class(raw: str | None) -> EncounterClass:
    """Normalize an Encounter.class code (ActCode or Synthea lowercase) to the canonical enum."""
    if not raw:
        return "OTHER"
    return _ENCOUNTER_CLASS_MAP.get(raw.strip().lower(), "OTHER")


def pick_primary_coding(codings: list[Coding], prefer: tuple[str, ...]) -> Coding | None:
    """Pick the primary coding: first whose normalized system is in ``prefer`` (in preference
    order), else the first coding with a code at all."""
    for system in prefer:
        for coding in codings:
            if coding.get("code") and normalize_system(coding.get("system")) == system:
                return coding
    for coding in codings:
        if coding.get("code"):
            return coding
    return None
