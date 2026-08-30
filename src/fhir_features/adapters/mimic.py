"""MIMIC-IV adapter — INTERFACE-ONLY STUB in this repository.

Compliance boundary (PhysioNet Credentialed DUA): MIMIC-IV data is local-only. It is never
committed to any repository, never sent to any cloud LLM or external API, and never appears in
fixtures, logs, or documentation. This stub exists so the canonical schema, loader, and
conformance suite are proven pluggable; the implementation lives in a separate, local-only
context where the credentialed data resides.

Planned mapping (implemented later, against the same CIR):

- ``patients``      -> PatientRow          (anchor_age-derived birth year: date_precision "year")
- ``admissions``    -> EncounterRow        (class "IMP"; admittime/dischtime; shifted dates are
                                            "day" precision — honest via date_precision)
- ``diagnoses_icd`` -> ConditionRow + ClaimDiagnosisRow (ICD9CM/ICD10CM via seq_num; the
                                            claims-shaped channel P4 needs)
- ``labevents``     -> ObservationRow      (d_labitems -> LOINC where mappable, else OTHER:)
- ``prescriptions`` -> MedicationRequestRow (starttime -> authored_date)

Configuration is env-only (never committed): ``MIMIC_DB_URL`` or ``MIMIC_CSV_DIR``, and the
path must resolve OUTSIDE the repository tree (enforced here even in the stub so the guardrail
is executable from day one).
"""

import os
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

from fhir_features.canonical.models import PatientRecordSet


class MimicConfigError(RuntimeError):
    """MIMIC configuration is missing or violates the local-only guardrail."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


class MimicAdapter:
    """Interface-only stub satisfying :class:`fhir_features.adapters.base.SourceAdapter`."""

    source: ClassVar[str] = "mimic"

    def __init__(self) -> None:
        csv_dir = os.environ.get("MIMIC_CSV_DIR")
        db_url = os.environ.get("MIMIC_DB_URL")
        if not csv_dir and not db_url:
            raise MimicConfigError(
                "set MIMIC_CSV_DIR or MIMIC_DB_URL in the environment (never in committed files)"
            )
        if csv_dir:
            resolved = Path(csv_dir).resolve()
            if resolved.is_relative_to(_repo_root()):
                raise MimicConfigError(
                    "MIMIC_CSV_DIR must resolve outside the repository tree — MIMIC data can "
                    "never live where it could be committed"
                )
            self.csv_dir: Path | None = resolved
        else:
            self.csv_dir = None
        self.db_url = db_url

    def iter_patient_records(self) -> Iterator[PatientRecordSet]:
        raise NotImplementedError(
            "The MIMIC-IV adapter is implemented in a separate local-only context; this "
            "repository ships only the contract. See the module docstring for the mapping plan."
        )
