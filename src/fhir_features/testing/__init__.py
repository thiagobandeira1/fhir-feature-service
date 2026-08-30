"""Distributable testing utilities — shipped inside the wheel so downstream adapter
implementations (the future local-only MIMIC repo) can import and run the identical
conformance contract this repo's Synthea adapter passes in CI."""

from fhir_features.testing.conformance import AdapterConformanceSuite, assert_conforms

__all__ = ["AdapterConformanceSuite", "assert_conforms"]
