"""Synthea FHIR R4 bundle adapter.

``record_set_from_bundle`` is the single bundle -> :class:`PatientRecordSet` function; the API
ingest route and the directory-walking file adapter share it, so CLI and HTTP ingestion produce
identical rows by construction.
"""

import gzip
import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, ClassVar

from fhir_features.canonical.models import (
    ClaimDiagnosisRow,
    CodingRow,
    ConditionRow,
    EncounterRow,
    ImmunizationRow,
    MedicationRequestRow,
    ObservationRow,
    ParseIssue,
    PatientRecordSet,
    PatientRow,
    ProcedureRow,
)
from fhir_features.fhir.bundle import (
    BundleValidationError,
    build_reference_map,
    validate_bundle,
)
from fhir_features.fhir.extractors.claim import extract_claim_diagnoses
from fhir_features.fhir.extractors.condition import extract_condition
from fhir_features.fhir.extractors.encounter import extract_encounter
from fhir_features.fhir.extractors.immunization import extract_immunization
from fhir_features.fhir.extractors.medication_request import extract_medication_request
from fhir_features.fhir.extractors.observation import extract_observation
from fhir_features.fhir.extractors.patient import extract_patient
from fhir_features.fhir.extractors.procedure import extract_procedure

SOURCE = "synthea"

#: Resource types this service parses; everything else is counted in ``skipped``.
_PARSED_TYPES = frozenset(
    {
        "Patient",
        "Encounter",
        "Condition",
        "Observation",
        "Procedure",
        "MedicationRequest",
        "Immunization",
        "Claim",
    }
)


def record_set_from_bundle(payload: Any) -> PatientRecordSet:
    """Parse one validated bundle into a PatientRecordSet.

    Raises :class:`BundleValidationError` for envelope problems (including an unextractable
    Patient — the whole model hangs off that row).
    """
    entries = validate_bundle(payload)
    refmap = build_reference_map(entries)

    patient: PatientRow | None = None
    encounters: list[EncounterRow] = []
    conditions: list[ConditionRow] = []
    observations: list[ObservationRow] = []
    procedures: list[ProcedureRow] = []
    medication_requests: list[MedicationRequestRow] = []
    immunizations: list[ImmunizationRow] = []
    claim_diagnoses: list[ClaimDiagnosisRow] = []
    codings: list[CodingRow] = []
    skipped: dict[str, int] = {}
    warnings: list[ParseIssue] = []
    claim_entries: list[tuple[Mapping[str, Any], str]] = []

    for i, entry in enumerate(entries):
        resource: Mapping[str, Any] = entry["resource"]
        resource_type = resource["resourceType"]
        pointer = f"/entry/{i}/resource"

        if resource_type == "Patient":
            patient, issues = extract_patient(resource, pointer)
            warnings.extend(issues)
        elif resource_type == "Encounter":
            enc, issues = extract_encounter(resource, refmap, pointer)
            if enc is not None:
                encounters.append(enc)
            warnings.extend(issues)
        elif resource_type == "Condition":
            cond, cond_codings, issues = extract_condition(resource, refmap, pointer)
            if cond is not None:
                conditions.append(cond)
                codings.extend(cond_codings)
            warnings.extend(issues)
        elif resource_type == "Observation":
            obs_rows, issues = extract_observation(resource, refmap, pointer)
            observations.extend(obs_rows)
            warnings.extend(issues)
        elif resource_type == "Procedure":
            proc, proc_codings, issues = extract_procedure(resource, refmap, pointer)
            if proc is not None:
                procedures.append(proc)
                codings.extend(proc_codings)
            warnings.extend(issues)
        elif resource_type == "MedicationRequest":
            med, issues = extract_medication_request(resource, refmap, pointer)
            if med is not None:
                medication_requests.append(med)
            warnings.extend(issues)
        elif resource_type == "Immunization":
            imm, issues = extract_immunization(resource, refmap, pointer)
            if imm is not None:
                immunizations.append(imm)
            warnings.extend(issues)
        elif resource_type == "Claim":
            claim_entries.append((resource, pointer))  # second pass: needs extracted conditions
        else:
            skipped[resource_type] = skipped.get(resource_type, 0) + 1

    if patient is None:
        raise BundleValidationError(
            "patient_unextractable", "the bundle's Patient resource could not be extracted"
        )

    conditions_by_id = {c.condition_id: c for c in conditions}
    for resource, pointer in claim_entries:
        diags, issues = extract_claim_diagnoses(resource, refmap, conditions_by_id, pointer)
        claim_diagnoses.extend(diags)
        warnings.extend(issues)

    return PatientRecordSet(
        source=SOURCE,
        patient=patient,
        encounters=encounters,
        conditions=conditions,
        observations=observations,
        procedures=procedures,
        medication_requests=medication_requests,
        immunizations=immunizations,
        claim_diagnoses=claim_diagnoses,
        codings=codings,
        skipped=skipped,
        warnings=warnings,
    )


def load_bundle_file(path: Path) -> Any:
    """Read a bundle JSON file (.json or .json.gz)."""
    if path.name.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    return json.loads(path.read_text(encoding="utf-8"))


class SyntheaBundleAdapter:
    """Walks a directory of Synthea bundle files into patient record sets, deterministically."""

    source: ClassVar[str] = SOURCE

    def __init__(self, bundle_dir: Path) -> None:
        self.bundle_dir = bundle_dir

    def bundle_files(self) -> list[Path]:
        return sorted(
            p
            for p in self.bundle_dir.iterdir()
            if p.name.endswith(".json") or p.name.endswith(".json.gz")
        )

    def iter_patient_records(self) -> Iterator[PatientRecordSet]:
        for path in self.bundle_files():
            yield record_set_from_bundle(load_bundle_file(path))
