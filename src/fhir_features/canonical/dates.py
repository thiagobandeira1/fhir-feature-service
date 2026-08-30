"""FHIR date/dateTime parsing.

The one rule that keeps every window feature honest: the ``local_date`` is derived from the
source-local datetime string BEFORE any UTC conversion. Converting first would shift an evening
encounter recorded at ``-05:00`` into the next calendar day and corrupt every date-window
feature (see ADR-0006).
"""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal

DatePrecision = Literal["second", "day", "month", "year"]

_YEAR_RE = re.compile(r"^(\d{4})$")
_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
_DAY_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


@dataclass(frozen=True)
class ParsedDateTime:
    """A FHIR date/dateTime decomposed into what the canonical layer stores."""

    utc_ts: datetime | None
    """UTC instant when the source carried a time; None for date-only precisions."""

    local_date: date
    """Calendar date in the SOURCE's local frame (year/month precisions impute the first day —
    an optimistic approximation kept visible via ``precision``)."""

    precision: DatePrecision


def parse_fhir_datetime(value: str) -> ParsedDateTime | None:
    """Parse a FHIR ``date``/``dateTime`` string; return None for garbage (caller warns).

    Handles the four FHIR precisions: YYYY, YYYY-MM, YYYY-MM-DD, and full timestamps
    (offset required by FHIR when a time is present; a trailing ``Z`` is normalized).
    """
    if not value:
        return None
    if m := _YEAR_RE.match(value):
        return ParsedDateTime(None, date(int(m[1]), 1, 1), "year")
    if m := _MONTH_RE.match(value):
        try:
            return ParsedDateTime(None, date(int(m[1]), int(m[2]), 1), "month")
        except ValueError:
            return None
    if m := _DAY_RE.match(value):
        try:
            return ParsedDateTime(None, date(int(m[1]), int(m[2]), int(m[3])), "day")
        except ValueError:
            return None
    if "T" not in value:
        # FHIR requires dashed dates; fromisoformat would accept compact forms like 20150314.
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        # FHIR requires an offset with a time; tolerate its absence by treating as UTC.
        parsed = parsed.replace(tzinfo=UTC)
    # Local calendar date FIRST (source frame), then the UTC instant.
    return ParsedDateTime(parsed.astimezone(UTC), parsed.date(), "second")
