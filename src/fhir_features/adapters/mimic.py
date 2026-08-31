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

#: URL schemes whose data lives in a local file we can (and must) path-check.
_FILE_BACKED_SCHEMES = ("duckdb:", "sqlite:", "file:")
_SERVER_SCHEMES = ("postgresql:", "postgres:")


class MimicConfigError(RuntimeError):
    """MIMIC configuration is missing or violates the local-only guardrail."""


def _enclosing_git_repo(path: Path) -> Path | None:
    """Walk up from ``path`` looking for a git work tree; None when outside any repo."""
    for candidate in [path, *path.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def _assert_outside_any_repo(target: Path, what: str) -> None:
    """The executable guardrail: MIMIC data may never live inside a git work tree.

    Anchored to git detection (not this package's location, which sits in site-packages once
    installed): a repo-resident data path is one ``git add -f`` away from being committed.
    """
    resolved = target.resolve()
    repo = _enclosing_git_repo(resolved)
    if repo is not None:
        raise MimicConfigError(
            f"{what} resolves inside the git repository at {repo} — MIMIC data can never "
            "live where it could be committed"
        )
    cwd_repo = _enclosing_git_repo(Path.cwd().resolve())
    if cwd_repo is not None and resolved.is_relative_to(cwd_repo):
        raise MimicConfigError(
            f"{what} resolves inside the current working repository — MIMIC data can never "
            "live where it could be committed"
        )


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
        self.csv_dir: Path | None = None
        if csv_dir:
            _assert_outside_any_repo(Path(csv_dir), "MIMIC_CSV_DIR")
            self.csv_dir = Path(csv_dir).resolve()
        if db_url:
            lowered = db_url.lower()
            if lowered.startswith(_FILE_BACKED_SCHEMES):
                # Strip scheme (and optional ///) to the embedded file path and check it.
                _, _, raw_path = db_url.partition(":")
                _assert_outside_any_repo(Path(raw_path.lstrip("/") or "."), "MIMIC_DB_URL path")
            elif not lowered.startswith(_SERVER_SCHEMES):
                if "://" in db_url:
                    raise MimicConfigError(
                        "MIMIC_DB_URL scheme not recognized — use postgresql:// or a local "
                        "duckdb:/sqlite: path"
                    )
                # No scheme at all: treat it as a bare file path.
                _assert_outside_any_repo(Path(db_url), "MIMIC_DB_URL path")
        self.db_url = db_url

    def iter_patient_records(self) -> Iterator[PatientRecordSet]:
        raise NotImplementedError(
            "The MIMIC-IV adapter is implemented in a separate local-only context; this "
            "repository ships only the contract. See the module docstring for the mapping plan."
        )
