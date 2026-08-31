"""Minimal RFC 5545 writer for the calendar subset emitted by the app."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from resume_tailor_harness.tracking.tables import utcnow

_PRODID = "-//resume-tailor-harness//application timeline//EN"
_LINE_OCTETS = 75


@dataclass(frozen=True)
class CalendarEntry:
    uid: str
    summary: str
    start: datetime
    end: datetime | None = None
    all_day: bool = False
    timezone: str | None = None
    location: str | None = None
    url: str | None = None
    description: str | None = None
    alarm_minutes_before: int | None = None


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


def _escape_text(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\r", "\\n")
        .replace("\n", "\\n")
    )


def _escape_uri(value: str) -> str:
    return value.replace("\r", "%0D").replace("\n", "%0A")


def _fold(line: str) -> list[str]:
    """Fold a content line at 75 UTF-8 octets, including continuation space."""
    if len(line.encode("utf-8")) <= _LINE_OCTETS:
        return [line]
    parts: list[str] = []
    current = ""
    limit = _LINE_OCTETS
    for character in line:
        candidate = current + character
        if current and len(candidate.encode("utf-8")) > limit:
            parts.append(current)
            current = character
            limit = _LINE_OCTETS - 1
        else:
            current = candidate
    if current:
        parts.append(current)
    return [parts[0], *(f" {part}" for part in parts[1:])]


def _utc_value(moment: datetime) -> str:
    return _aware(moment).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _timed_value(moment: datetime, timezone_name: str | None) -> tuple[str, str]:
    if timezone_name:
        local = _aware(moment).astimezone(ZoneInfo(timezone_name))
        return f";TZID={timezone_name}", local.strftime("%Y%m%dT%H%M%S")
    return "", _utc_value(moment)


def _entry_lines(entry: CalendarEntry, stamp: datetime) -> list[str]:
    lines = [
        "BEGIN:VEVENT",
        f"UID:{entry.uid}",
        f"DTSTAMP:{_utc_value(stamp)}",
        f"SUMMARY:{_escape_text(entry.summary)}",
    ]
    if entry.all_day:
        start_date = _aware(entry.start).date()
        end_date = (
            _aware(entry.end).date() if entry.end else start_date + timedelta(days=1)
        )
        lines.extend(
            [
                f"DTSTART;VALUE=DATE:{start_date:%Y%m%d}",
                f"DTEND;VALUE=DATE:{end_date:%Y%m%d}",
            ]
        )
    else:
        end = entry.end or _aware(entry.start) + timedelta(hours=1)
        start_parameter, start_value = _timed_value(entry.start, entry.timezone)
        end_parameter, end_value = _timed_value(end, entry.timezone)
        lines.extend(
            [
                f"DTSTART{start_parameter}:{start_value}",
                f"DTEND{end_parameter}:{end_value}",
            ]
        )
    if entry.location:
        lines.append(f"LOCATION:{_escape_text(entry.location)}")
    if entry.url:
        lines.append(f"URL:{_escape_uri(entry.url)}")
    if entry.description:
        lines.append(f"DESCRIPTION:{_escape_text(entry.description)}")
    if entry.alarm_minutes_before and not entry.all_day:
        lines.extend(
            [
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{_escape_text(entry.summary)}",
                f"TRIGGER:-PT{entry.alarm_minutes_before}M",
                "END:VALARM",
            ]
        )
    lines.append("END:VEVENT")
    return lines


def render_calendar(
    entries: list[CalendarEntry], *, now: datetime | None = None
) -> str:
    stamp = now or utcnow()
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{_PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    for entry in entries:
        lines.extend(_entry_lines(entry, stamp))
    lines.append("END:VCALENDAR")
    folded = [folded_line for line in lines for folded_line in _fold(line)]
    return "\r\n".join(folded) + "\r\n"
