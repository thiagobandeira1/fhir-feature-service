# ADR-0006: Partial dates — source-local derived DATE, UTC timestamp, explicit precision

## Status

Accepted

## Date

2026-08-30

## Context

FHIR `date`/`dateTime` values arrive at four precisions — `YYYY`, `YYYY-MM`, `YYYY-MM-DD`, and
full timestamps with a UTC offset. Two classic bugs live here:

1. **The UTC date shift.** An encounter at `2023-03-14T21:30:00-05:00` is `2023-03-15` in UTC.
   If the DATE column is derived *after* UTC conversion, every evening event in a western-offset
   source slides into the next calendar day, silently corrupting every date-window feature
   (`encounters_365d`, `has_diabetes` at a boundary `as_of`, etc.).
2. **Silent precision loss.** Coercing `2019` or `2019-05` into a full timestamp makes a
   year-precision onset indistinguishable from a known exact date.

A single-column answer (only a timestamp, or only a date) cannot serve both the feature layer
(which reasons in calendar dates, per ADR-0005) and consumers that want real instants (P1 needs
observation times).

## Decision

`parse_fhir_datetime()` (in `canonical/dates.py`) decomposes every date-bearing field into three
stored values:

- **`utc_ts`** — the UTC instant, populated only when the source carried a time (TIMESTAMP
  columns). A time without an offset is tolerated as UTC despite FHIR requiring an offset.
- **`local_date`** — the calendar date taken from the source-local string **before** any UTC
  conversion (DATE columns). Year and month precisions impute the first day
  (`2019` → `2019-01-01`, `2019-05` → `2019-05-01`).
- **`precision`** — `second | day | month | year`, stored as `date_precision` alongside every
  derived date, so imputation is never invisible.

Garbage strings return `None`; the caller records a warning (or drops the row when the date is
required) rather than raising — input is untrusted (spec §6). The feature inclusion rule
(event DATE ≤ `as_of`) always compares `local_date` values.

## Consequences

- The evening-at-`-05:00` case keeps its local calendar date; this is pinned by a dedicated unit
  test, because it is the single easiest regression to reintroduce during refactoring.
- **Year/month precision imputes Jan-1/first-of-month optimistically.** A condition onset
  recorded as `2019` counts as active from 2019-01-01, up to ~a year earlier than reality. This
  biases chronic flags and lookback windows toward inclusion. We chose optimistic-and-visible
  over pessimistic-or-dropped: `date_precision` travels with every date so consumers can filter
  or discount imputed values, but nothing forces them to look at it.
- Storage cost: three columns where naive designs have one, on every dated entity.
- `utc_ts` is NULL for date-only precisions, so consumers wanting instants must handle NULL;
  conversely, ordering ties on `local_date` are broken by id, not time, for date-only events.
- Tolerating offset-less times as UTC is a lenient reading of the FHIR spec; it avoids dropping
  otherwise-good rows but can mislabel the instant by up to a day's worth of offset. The
  `local_date` is unaffected, which is why feature logic never touches `utc_ts`.
- Cross-source comparability depends on every adapter honoring the same contract (local date
  before conversion, honest precision); the adapter conformance suite checks precision enums
  and no-events-before-birth, but cannot detect a source that converted first.
