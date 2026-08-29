# Calendar export developer reference

Loads only when working under `src/resume_agent/calendar/`. Two modules, split
deliberately: `ics.py` knows RFC 5545 and nothing about the domain; `events.py`
maps an `ApplicationEvent` onto a `CalendarEntry`. The split is what lets the
serializer's folding and escaping rules be tested as pure text, with no ORM in
scope.

## Hand-rolled, not `icalendar`

The subset this app emits is a few dozen lines, and the only parts worth testing
are the folding and escaping rules — which a dependency would not exempt us
from understanding. `icalendar` would be a new runtime dependency for that.

## Four rules that are easy to get wrong

- **CRLF, always.** `render_calendar` joins on `\r\n` and ends with one. A bare
  `\n` is not a line break in RFC 5545, and lenient clients hide the mistake
  until a strict one rejects the whole file.
- **`DTEND` is exclusive for date values.** A one-day all-day event ends
  *tomorrow*: `DTSTART;VALUE=DATE:20260309` pairs with
  `DTEND;VALUE=DATE:20260310`. Emitting the same date produces a zero-length
  event that some clients drop entirely.
- **Lines fold at 75 octets, and continuations begin with one space** — which
  itself costs an octet, so `_fold` drops its limit to 74 after the first
  chunk. Folding counts *octets*, not characters: a multi-byte character
  straddling the boundary corrupts the line, which is why `_fold` measures
  `char.encode("utf-8")` rather than slicing the string.
- **TEXT and URI escape differently.** `_escape_text` escapes `\`, `;`, `,` and
  newlines for `SUMMARY`/`DESCRIPTION`/`LOCATION`; `_escape_uri` does **not** —
  a URL's commas and semicolons are structural, and escaping them yields a
  link that does not resolve. Do not collapse these two functions.

## Lead times split by owner

No poller can deliver a short-lead reminder well. The tick is hourly
(`REMINDER_INTERVAL_SECONDS = 3600`), so a "one hour before" nudge would smear
across most of its own lead time. So:

| lead | owner | mechanism |
| --- | --- | --- |
| ~1 hour before | the viewer's calendar | `VALARM` / `TRIGGER:-PT60M`, set in `events.py` |
| 24h before an interview | this app | `Notification`, `Settings.interview_reminder_hours` |
| 48h before an offer deadline | this app | `Notification`, `Settings.offer_deadline_reminder_days` |

`VALARM` fires natively, on the user's phone, with no server involved — which
is what calendars are for. **All-day events carry no alarm**
(`alarm_minutes_before=None if event.all_day`): there is no meaningful hour to
alarm against, and a midnight buzz for "you applied on the 3rd" is noise.

Both config values are `ge=0` with `0` disabling that reminder, matching
`follow_up_days`.

## `UID` is stable, and that is load-bearing

`entry_for_event` derives `UID` from the event id
(`application-event-{id}@resume-agent`). Re-importing a re-downloaded `.ics`
therefore **updates** the existing calendar entry rather than duplicating it —
which is the whole recovery path for a rescheduled interview, since there is no
subscribable feed.

## No `webcal://` feed — deliberately

A subscribable feed is unauthenticated by construction: calendar clients send
no session cookie. Such a URL would expose every company applied to and every
interview date to anyone holding the link, permanently. It needs a per-user
capability token, a revoke path, and a rate limit under ADR-0008 — its own
design pass. Both routes in `api/routers/calendar.py` sit behind the ordinary
session guard instead, and generate on the fly (no stored artifact, so no
`artifact_path` involvement).

## Testing

`tests/test_ics.py` covers the serializer as pure text — wrapper, CRLF, all-day
vs timed, `TZID`, folding at the octet boundary, escaping, and alarms.
`tests/test_calendar_events.py` covers the domain mapping.

**Neither proves a real calendar client accepts the file.** RFC conformance and
client acceptance are different bars; that check is manual and belongs in the
release path, not the suite.
