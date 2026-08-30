"""Per-resource extractors: FHIR resource dict -> CIR row(s) + parse issues.

Shared conventions (every extractor follows the pattern set by ``patient.py``):

- Input is an untrusted ``Mapping`` — never index without a default; a missing/garbage field
  either degrades the row (optional column -> None) or drops the row with a ``ParseIssue``.
- ``pointer`` is the JSON pointer prefix of the resource (e.g. ``/entry/12/resource``); every
  ParseIssue pointer starts with it. Issue codes are stable snake_case tokens.
- Rows a resource cannot support (no id, no code, no usable date) return None/[] plus an issue;
  extractors never raise on content.
- Dates go through :func:`fhir_features.canonical.dates.parse_fhir_datetime`; codings through
  :mod:`fhir_features.canonical.codes` helpers.
"""
