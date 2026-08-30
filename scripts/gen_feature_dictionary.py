"""Generate ``docs/feature_dictionary.md`` from the feature registry.

The registry (``fhir_features.features.registry``) is the single source of truth for the
feature contract; a schema-contract test pins it to the actual SQL output. This script renders
it as a human-readable Markdown table so the docs can never drift from the code.

Usage::

    uv run python scripts/gen_feature_dictionary.py
"""

from pathlib import Path

from fhir_features.features.registry import AS_OF_SEMANTICS, FEATURE_VERSION, FEATURES
from fhir_features.features.value_sets import load_value_sets

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = REPO_ROOT / "docs" / "feature_dictionary.md"

HEADER_TEMPLATE = """\
# Feature dictionary — `{feature_version}`

> **Generated file — do not edit.** Regenerate with
> `uv run python scripts/gen_feature_dictionary.py`. The machine-readable equivalent is
> `GET /v1/features/schema`; a schema-contract test pins both to the actual SQL columns.

- **feature_version:** `{feature_version}` — stamped on every feature response. Additive
  columns do not bump it; semantic changes do (via ADR).
- **valuesets_version:** `{valuesets_version}` (CalVer) — version of the committed value-set
  JSON, also stamped on every feature response.
- **as_of semantics:** {as_of_semantics}. Features are computed at query time from the
  canonical event tables, so an event dated after `as_of` can never influence a feature at
  `as_of` (leakage-free by construction; proven by golden tests at two pinned dates).
- **Value-set caveat:** the value sets referenced below are **demo-grade** curated sets built
  from public code systems (SNOMED CT, LOINC, RxNorm, CVX) and cross-checked against the
  generated Synthea data. They are **not** NCQA HEDIS / VSAC licensed sets; a real measure
  program would swap in licensed sets.

| # | Name | Type | Nullable | Value set | Description |
|---|------|------|----------|-----------|-------------|
"""


def _escape(text: str) -> str:
    """Escape pipe characters so descriptions cannot break the Markdown table."""
    return text.replace("|", "\\|")


def render() -> str:
    valuesets_version = load_value_sets().version
    lines = [
        HEADER_TEMPLATE.format(
            feature_version=FEATURE_VERSION,
            valuesets_version=valuesets_version,
            as_of_semantics=AS_OF_SEMANTICS,
        )
    ]
    for index, spec in enumerate(FEATURES, start=1):
        value_set = f"`{spec.value_set_id}`" if spec.value_set_id else "—"
        lines.append(
            f"| {index} | `{spec.name}` | {spec.type} | {'yes' if spec.nullable else 'no'} "
            f"| {value_set} | {_escape(spec.description)} |\n"
        )
    return "".join(lines)


def main() -> int:
    OUTPUT_PATH.write_text(render(), encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT_PATH.relative_to(REPO_ROOT)} ({len(FEATURES)} features)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
