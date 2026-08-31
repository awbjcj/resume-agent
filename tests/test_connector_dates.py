from datetime import datetime, timezone

from resume_tailor_harness.discovery.connectors.dates import (
    parse_epoch_millis,
    parse_iso_datetime,
    parse_relative_posted_at,
)


def test_parses_iso_with_z():
    assert parse_iso_datetime("2026-06-01T12:00:00Z") == datetime(
        2026, 6, 1, 12, 0, tzinfo=timezone.utc
    )


def test_parses_iso_with_offset():
    out = parse_iso_datetime("2026-06-01T12:00:00+00:00")
    assert out == datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


def test_parses_iso_date_as_utc_midnight():
    assert parse_iso_datetime("2026-06-01") == datetime(2026, 6, 1, tzinfo=timezone.utc)


def test_returns_none_on_garbage_or_empty():
    assert parse_iso_datetime("not a date") is None
    assert parse_iso_datetime("") is None
    assert parse_iso_datetime(None) is None


def test_returns_none_on_non_string_value():
    assert parse_iso_datetime(123) is None


def test_parse_relative_posted_at_days_hours_minutes():
    now = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)
    assert parse_relative_posted_at("2 days ago", now=now) == datetime(
        2026, 6, 14, 12, 0, tzinfo=timezone.utc
    )
    assert parse_relative_posted_at("3 hours ago", now=now) == datetime(
        2026, 6, 16, 9, 0, tzinfo=timezone.utc
    )
    assert parse_relative_posted_at("15 minutes ago", now=now) == datetime(
        2026, 6, 16, 11, 45, tzinfo=timezone.utc
    )


def test_parse_relative_posted_at_returns_none_for_unknown():
    now = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)
    assert parse_relative_posted_at("promoted", now=now) is None
    assert parse_relative_posted_at(None, now=now) is None


def test_parse_epoch_millis_returns_utc_datetime():
    assert parse_epoch_millis(1748736000000) == datetime(
        2025, 6, 1, tzinfo=timezone.utc
    )


def test_parse_epoch_millis_returns_none_for_non_numeric_or_bool():
    assert parse_epoch_millis(None) is None
    assert parse_epoch_millis("1748736000000") is None
    assert parse_epoch_millis(True) is None
