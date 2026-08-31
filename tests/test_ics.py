from datetime import datetime, timezone

from resume_tailor_harness.calendar.ics import CalendarEntry, render_calendar

START = datetime(2026, 3, 9, 19, 0, tzinfo=timezone.utc)
STAMP = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)


def _entry(**over) -> CalendarEntry:
    values = {
        "uid": "event-1@resume-tailor-harness",
        "summary": "Technical round — Acme",
        "start": START,
        "end": datetime(2026, 3, 9, 20, 0, tzinfo=timezone.utc),
        "all_day": False,
        "timezone": None,
        "location": None,
        "url": None,
        "description": None,
        "alarm_minutes_before": 60,
    }
    values.update(over)
    return CalendarEntry(**values)


def test_calendar_uses_crlf_fixed_stamp_and_stable_uid() -> None:
    out = render_calendar([_entry()], now=STAMP)
    assert out.startswith("BEGIN:VCALENDAR\r\n")
    assert "\n" not in out.replace("\r\n", "")
    assert "DTSTAMP:20260301T120000Z" in out
    assert "UID:event-1@resume-tailor-harness" in out


def test_timed_utc_event_has_end_and_alarm() -> None:
    out = render_calendar([_entry()], now=STAMP)
    assert "DTSTART:20260309T190000Z" in out
    assert "DTEND:20260309T200000Z" in out
    assert "TRIGGER:-PT60M" in out


def test_named_timezone_converts_the_utc_instant_to_local_wall_time() -> None:
    out = render_calendar([_entry(timezone="America/New_York")], now=STAMP)
    assert "DTSTART;TZID=America/New_York:20260309T150000" in out
    assert "DTEND;TZID=America/New_York:20260309T160000" in out


def test_all_day_end_is_exclusive_and_has_no_alarm() -> None:
    out = render_calendar([_entry(all_day=True, end=None)], now=STAMP)
    assert "DTSTART;VALUE=DATE:20260309" in out
    assert "DTEND;VALUE=DATE:20260310" in out
    assert "BEGIN:VALARM" not in out


def test_timed_missing_end_defaults_to_one_hour() -> None:
    out = render_calendar([_entry(end=None)], now=STAMP)
    assert "DTEND:20260309T200000Z" in out


def test_text_escaping_and_utf8_octet_folding() -> None:
    out = render_calendar(
        [_entry(description="轮" * 80 + "; round, then\nlunch. Path C:\\temp")],
        now=STAMP,
    )
    assert r"\;" in out and r"\," in out and r"\n" in out and r"\\" in out
    assert "\r\n " in out
    assert all(len(line.encode("utf-8")) <= 75 for line in out.split("\r\n"))


def test_bare_carriage_returns_and_url_newlines_cannot_inject_properties() -> None:
    out = render_calendar(
        [
            _entry(
                location="Room A\rATTENDEE:mailto:attacker@example.com",
                url="https://example.com/meet\r\nATTENDEE:mailto:attacker@example.com",
            )
        ],
        now=STAMP,
    )
    assert "\r\nATTENDEE:" not in out
    assert "Room A\\nATTENDEE" in out
    assert "%0D%0AATTENDEE" in out


def test_empty_calendar_is_valid() -> None:
    out = render_calendar([], now=STAMP)
    assert "BEGIN:VCALENDAR" in out
    assert "BEGIN:VEVENT" not in out
