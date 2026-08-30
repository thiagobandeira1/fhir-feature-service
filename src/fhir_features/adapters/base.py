"""The SourceAdapter contract.

Deliberately minimal: an adapter is anything that yields fully normalized
:class:`~fhir_features.canonical.models.PatientRecordSet`s. The normalization burden sits ON
the adapter by contract — UTC timestamps plus source-local dates with honest precision,
normalized code-system short names, UCUM units, and source-native ids namespaced by the
``source`` token. The executable version of this contract is
:class:`fhir_features.testing.conformance.AdapterConformanceSuite`.

There is no runtime adapter registry: Synthea is wired directly, MIMIC ships as a stub.
"""

from collections.abc import Iterator
from typing import ClassVar, Protocol

from fhir_features.canonical.models import PatientRecordSet


class SourceAdapter(Protocol):
    """A data source that can be walked into canonical patient record sets."""

    source: ClassVar[str]

    def iter_patient_records(self) -> Iterator[PatientRecordSet]:
        """Yield one PatientRecordSet per patient. Must be repeatable (callable twice)."""
        ...
