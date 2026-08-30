"""Unit tests for FHIR date parsing — the local-date-before-UTC rule above all."""

from datetime import UTC, date, datetime

import pytest

from fhir_features.canonical.dates import parse_fhir_datetime


class TestPrecisions:
    def test_year_only(self) -> None:
        parsed = parse_fhir_datetime("2015")
        assert parsed is not None
        assert parsed.precision == "year"
        assert parsed.local_date == date(2015, 1, 1)
        assert parsed.utc_ts is None

    def test_year_month(self) -> None:
        parsed = parse_fhir_datetime("2015-03")
        assert parsed is not None
        assert parsed.precision == "month"
        assert parsed.local_date == date(2015, 3, 1)
        assert parsed.utc_ts is None

    def test_full_date(self) -> None:
        parsed = parse_fhir_datetime("2015-03-14")
        assert parsed is not None
        assert parsed.precision == "day"
        assert parsed.local_date == date(2015, 3, 14)
        assert parsed.utc_ts is None

    def test_full_timestamp_with_offset(self) -> None:
        parsed = parse_fhir_datetime("2015-03-14T15:30:00-05:00")
        assert parsed is not None
        assert parsed.precision == "second"
        assert parsed.utc_ts == datetime(2015, 3, 14, 20, 30, tzinfo=UTC)

    def test_zulu_suffix(self) -> None:
        parsed = parse_fhir_datetime("2015-03-14T15:30:00Z")
        assert parsed is not None
        assert parsed.utc_ts == datetime(2015, 3, 14, 15, 30, tzinfo=UTC)


class TestLocalDateRule:
    def test_evening_negative_offset_keeps_local_calendar_date(self) -> None:
        """An 11 PM encounter at -05:00 is 4 AM next-day UTC — the DATE must stay local."""
        parsed = parse_fhir_datetime("2019-06-30T23:15:00-05:00")
        assert parsed is not None
        assert parsed.local_date == date(2019, 6, 30)  # NOT July 1
        assert parsed.utc_ts == datetime(2019, 7, 1, 4, 15, tzinfo=UTC)

    def test_early_positive_offset_keeps_local_calendar_date(self) -> None:
        parsed = parse_fhir_datetime("2019-07-01T00:30:00+02:00")
        assert parsed is not None
        assert parsed.local_date == date(2019, 7, 1)  # NOT June 30
        assert parsed.utc_ts == datetime(2019, 6, 30, 22, 30, tzinfo=UTC)

    def test_naive_timestamp_treated_as_utc(self) -> None:
        parsed = parse_fhir_datetime("2019-06-30T23:15:00")
        assert parsed is not None
        assert parsed.local_date == date(2019, 6, 30)
        assert parsed.utc_ts == datetime(2019, 6, 30, 23, 15, tzinfo=UTC)


class TestGarbage:
    @pytest.mark.parametrize(
        "value",
        ["", "not-a-date", "20150314", "2015-13", "2015-02-30", "2015-00-01", "15-03-14"],
    )
    def test_garbage_returns_none(self, value: str) -> None:
        assert parse_fhir_datetime(value) is None
