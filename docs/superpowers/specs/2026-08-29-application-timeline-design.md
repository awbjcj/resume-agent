# Application timeline, calendar export, and funnel analytics — design

**Date:** 2026-08-29
**Status:** Approved, awaiting implementation plan

## Problem

`Application` (`tracking/tables.py:113`) is a state-machine *snapshot*, not a
history:

| field | meaning |
| --- | --- |
| `status` | `ready` / `submitted` / `interview` / `offer` / `rejected` / `closed` |
| `submitted_at` | stamped once, when status first becomes `submitted` |
| `notes` | one free-text string, rendered as a single-line `<input>` |
| `updated_at` | last write |

Everything a job hunt actually consists of — the recruiter call on the 4th, the
online assessment due the 9th, three technical rounds on three platforms across
two weeks, what was asked in each, how each went, the offer, its number, and the
72 hours you have to answer it — collapses into one enum value and one line of
text.

Two consequences follow.

**Nothing can be reconstructed.** By the time you have twelve applications in
flight you cannot answer "when did Stripe last contact me?" or "is day-12
silence from Datadog normal or terminal?" The data was never recorded.

**Analytics cannot answer a single time question.** `tracking/analytics.py` is
pure cohort counting — applications / responses / interviews / offers, sliced by
`source` and by `fit_score` band. There is no time dimension anywhere in the
module, because outside `submitted_at` no stage has ever carried a timestamp.
Cycle time, stage drop-off, and time-to-first-response are not merely unbuilt;
they are unbuildable against the current schema.

### Two latent defects this work surfaces

Both are pre-existing. Both sit directly in the path of this feature.

**Stale-application reminders only work for Gmail-connected users.**
`create_follow_up_reminders` has exactly one call site — `services/gmail_sync.py:45`,
*inside* `run_gmail_sync`, which calls `build_service()` on line 36 and raises
first when there is no token. `gmail/scheduler.py` only iterates users owning a
`gmail_token.json`. A user who never connects Gmail silently receives no
reminders at all, and nothing documents this coupling.

**Touching the Tracking tab makes a job permanently undeletable.**
`upsert_application` (`services/board.py:356`) creates an `Application` row
unconditionally, and `has_progress` (`tracking/repository.py:470`) returns
`True` if *any* `Application` row exists. Saving status `ready` with no notes —
a no-op by any reasonable reading — permanently trips the `delete_job` gate.

## Goals

- Record the full timeline of an application: every stage, dated, with modality,
  platform, notes, and reflection.
- Read it back per-job (chronological) and across jobs (a spreadsheet grid), and
  export it.
- Put dated events on the user's real calendar, with alarms.
- Produce funnel and cycle-time analytics that are honest about small samples.

## Non-goals

- **Google Calendar API write access.** Rejected in favour of `.ics`. Adding
  `calendar.events` to the OAuth grant is a substantial consent escalation on an
  integration deliberately scoped to `gmail.readonly` + `gmail.compose`, drafts
  only, `gmail.send` permanently out of scope. `.ics` also covers Outlook,
  Apple, and Tencent, which the Google API does not.
- **A subscribable calendar feed** (`webcal://`). Deferred with its security
  work named — see "Deferred, with reasons".
- **Gmail proposing events.** Deferred — see the same section.
- **Any LLM.** This feature is deterministic CRUD, date arithmetic, and
  aggregation end to end. No spend gate, no model routing, no eval impact.

---

## Data model

### `ApplicationEvent` — new table

One row per timeline entry. Chosen over wide columns on `Application` because
the round count is unbounded (Amazon loops run five; a company can add a
team-match call mid-process), because wide columns would make "add a fourth
round" a schema migration, and because the spreadsheet the user asked for is a
*presentation* of a timeline rather than its storage.

```python
class ApplicationEvent(SQLModel, table=True):
    __tablename__ = "application_events"

    id: int | None = Field(default=None, primary_key=True)
    application_id: int = Field(foreign_key="applications.id", index=True)

    kind: str = Field(index=True)              # EventKind value
    custom_label: str | None = None            # required iff kind == "custom"
    sequence: int = 1                          # nth event of this kind

    occurred_at: datetime | None = Field(default=None, index=True)  # UTC
    all_day: bool = False
    timezone: str | None = None                # IANA, e.g. "America/New_York"
    duration_minutes: int | None = None

    modality: str | None = None                # Modality value
    platform: str | None = None                # Platform value
    platform_other: str | None = None          # required iff platform == "other"
    location_or_link: str | None = None
    interviewers: str | None = None

    result: str = Field(default="pending", index=True)   # EventResult value
    notes: str | None = None                   # markdown
    reflection: str | None = None              # markdown

    # offer_received only
    comp_base: int | None = None
    comp_bonus: int | None = None
    comp_equity_annual: int | None = None
    comp_signing: int | None = None
    comp_currency: str | None = None           # ISO 4217

    source: str = Field(default="manual")      # manual | migration | gmail
    schema_version: int = 1
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
```

### Vocabularies

```python
class EventKind(str, Enum):
    application_submitted = "application_submitted"
    recruiter_screen      = "recruiter_screen"      # "HR call"
    online_assessment     = "online_assessment"     # timed coding challenge
    questionnaire         = "questionnaire"         # behavioural / culture form
    technical_phone_screen = "technical_phone_screen"
    technical_round       = "technical_round"       # repeatable
    system_design         = "system_design"
    behavioral            = "behavioral"
    hiring_manager        = "hiring_manager"
    onsite_loop           = "onsite_loop"
    team_match            = "team_match"
    offer_received        = "offer_received"        # repeatable (negotiation)
    offer_deadline        = "offer_deadline"
    rejected              = "rejected"
    withdrawn             = "withdrawn"
    custom                = "custom"                # excluded from funnel charts
```

`online_assessment` and `questionnaire` are separate kinds: a timed
HackerRank challenge and a Pymetrics culture form are different artifacts with
different preparation and different pass semantics, and collapsing them makes
the funnel unreadable.

```python
class Modality(str, Enum):
    onsite = "onsite"; virtual = "virtual"; phone = "phone"; async_ = "async"

class Platform(str, Enum):
    zoom = "zoom"; teams = "teams"; google_meet = "google_meet"
    webex = "webex"; tencent_meeting = "tencent_meeting"; feishu = "feishu"
    phone = "phone"; hackerrank = "hackerrank"; codesignal = "codesignal"
    coderpad = "coderpad"; karat = "karat"; other = "other"

class EventResult(str, Enum):
    pending = "pending"; advanced = "advanced"; rejected = "rejected"
    no_response = "no_response"; cancelled = "cancelled"; withdrew = "withdrew"
```

`no_response` exists because ghosting is not rejection. Conflating them
overstates the rejection rate and understates the response-rate problem, which
are different problems with different fixes.

### Why these fields and not others

`duration_minutes` and `location_or_link` are not conveniences — the `.ics`
export is incoherent without them. A VEVENT requires an end time; defaulting a
four-hour onsite loop to sixty minutes writes a wrong block into the user's
calendar. `LOCATION`/`URL` is what makes the calendar entry actionable at 8:58am.

`interviewers` is free text, deliberately not a relation. The repo already has
an `EmailDraft` type `thank_you` (`tracking/tables.py:169`); names recorded here
are what that draft needs. Modelling people as entities returns nothing further.

### Timing is derived; result is stored

Two orthogonal questions get conflated into a single "outcome" field and corrupt
the funnel: *has this happened yet* and *did I pass*.

- **Timing is never stored.** `occurred_at > now()` means upcoming, otherwise
  past. A stored flag goes stale silently.
- **Result is stored explicitly**, as `EventResult` above.

### Date precision and timezone

`occurred_at` is UTC. `all_day` distinguishes "I applied on the 3rd" from "Zoom
at 14:00". `timezone` holds an IANA name (defaulted from the browser at entry),
not a UTC offset, because DST can shift between logging an event and its
occurrence — and because interviews are routinely scheduled in the recruiter's
zone, not the candidate's.

This mirrors how iCalendar itself models the distinction, so `.ics` generation
is a direct mapping: `all_day` events emit `DTSTART;VALUE=DATE`, timed events
emit `DTSTART;TZID=<timezone>`.

### Compensation lives on the event

Structured (`base`, `bonus`, `equity_annual`, `signing`, `currency`), with total
compensation **derived, never stored**. Offers are quoted as components;
collapsing them at entry destroys information that cannot be recovered, and a
derived TC still gives the charts one comparable number.

`offer_received` is repeatable. A negotiated revision is a *new* event with its
own numbers, so negotiation history is a free byproduct of the event log and
needs no additional table. "Current offer" is the latest `offer_received` by
`occurred_at`.

`offer_deadline` stays an event kind rather than a `deadline_at` field on the
offer event. Both the reminder engine and the `.ics` exporter then handle
exactly one kind of thing uniformly; as a field, each would need a special case.
An orphan deadline with no offer is harmless.

### Application status: progression versus terminal

The Round-1 rule "status is a forward-only high-water mark" does not survive
contact with reality — `ApplicationStatus` has no ordering, and `rejected` is
not *behind* `interview`, it is an *exit*. A naive high-water mark blocks the
single most common transition in a job hunt.

The rule is therefore:

- **Progression** — `ready < submitted < interview < offer` — advances
  forward only. Logging a technical round cannot demote an offer.
- **Terminal** — `rejected`, `closed` — is reachable from *any* state,
  including `offer` (rescinded offers happen).

This mirrors `gmail/propose.py:13`'s existing `_TERMINAL = {rejected, closed}`
rather than inventing a second rule. Events auto-advance status under it;
manual override and Gmail proposals continue to write status directly.

Kind-to-status mapping, applied on event create and update:

| event kind | implies status |
| --- | --- |
| `application_submitted` | `submitted` |
| `recruiter_screen`, `online_assessment`, `questionnaire`, `technical_phone_screen`, `technical_round`, `system_design`, `behavioral`, `hiring_manager`, `onsite_loop`, `team_match` | `interview` |
| `offer_received`, `offer_deadline` | `offer` |
| `rejected` | `rejected` (terminal) |
| `withdrawn` | `closed` (terminal) |
| `custom` | no change |

Two clarifications this table would otherwise leave ambiguous:

- **`result` never moves status.** A `technical_round` with
  `result="rejected"` means that round went badly, not that the application is
  dead — companies advance candidates past weak rounds. Only a `rejected`
  *event* is terminal.
- **Deleting an event never moves status back.** Progression is forward-only,
  so a mis-logged event that advanced status is undone by the manual override,
  not by deletion.

**This amends an invariant documented in `tracking/CLAUDE.md` and requires an
ADR.**

### Validation: almost none

The real funnel is not a clean sequence. Candidates are referred straight to
onsites, recruiters skip the OA, companies reorder loops, and offers arrive for
roles never formally applied to. Every ordering rule has a real counterexample,
and a tracker that argues about what happened is worse than useless.

Enforced:

- `occurred_at` non-null on every kind except `custom`.
- `custom_label` required iff `kind == "custom"`; `platform_other` required iff
  `platform == "other"`.
- `kind` and every enum field must be a known value (422 otherwise, matching
  `upsert_application`'s existing pattern at `api/routers/jobs.py:288`).

Warned, not blocked: a duplicate `(kind, sequence)` pair.

`sequence` is auto-assigned as the nth event of its kind ordered by
`occurred_at` — nulls last, tie-broken by `created_at` — with a manual override.
Rounds are logged in order roughly always, and the override covers the
remainder. Inserting a forgotten earlier round renumbers the later ones unless
they carry an override.

### `has_progress` — enforcing the stated intent

`has_progress`'s docstring says it protects "user investment that must never be
destroyed". An empty `ready` `Application` row is definitionally not that. The
predicate is refined so an `Application` counts only when it carries actual
investment:

```
status != "ready"
  OR notes is non-empty
  OR any ApplicationEvent exists
  OR resume_version_id / cover_letter_id is set
```

`ResumeVersion` and `CoverLetter` existence checks are unchanged, as is the
`job.status in {approved, tailored, rendered}` check. `progressed_job_ids`
(`tracking/repository.py:483`) must be updated in lockstep — it exists to batch
exactly this predicate and would otherwise silently diverge.

This **loosens a destructive-action gate** and needs tests pinning both
directions: an empty `ready` row deletes; a row with one event refuses. It also
un-sticks jobs already stuck in existing databases. **Requires an ADR.**

### Migration

Hand-rolled `ensure_*` functions in `tracking/migrate.py`, matching every other
schema change in this repo (no Alembic):

- `ensure_application_events_table(engine)` — create table + indexes.
- `ensure_application_submitted_events(engine)` — for each `Application` with a
  non-null `submitted_at` and no existing `application_submitted` event, emit
  one (`all_day=True`, `result="advanced"`, `source="migration"`). Idempotent.

Status is **not** backfilled into synthetic events. An `interview` status
implies some interview happened but carries no date, and an undated synthetic
event pollutes precisely the cycle-time and funnel numbers this feature exists
to produce. A visibly incomplete history beats a plausibly wrong one. The
`source="migration"` tag keeps migrated events distinguishable permanently.

---

## Reminders

### Decoupling from Gmail

Reminder generation moves out of `run_gmail_sync` into its own scheduler tick
running **hourly for every user**, independent of Gmail connection state.
`run_gmail_sync` stops calling `create_follow_up_reminders`; episode-keyed
dedupe in `Notification.message_id` makes the transition safe. Existing
stale-application reminders move with it and start working for users who never
connected Gmail — a pre-existing bug fixed as a precondition, not new scope.

### Who owns which lead time

No poller can deliver short-lead reminders well. Coupled to Gmail today, at
`gmail_sync_interval_hours` (default 6), a "one hour before" reminder lands
anywhere from one to seven hours early; even on the hourly tick above it still
smears across a full hour, which is most of the lead time. Rather than tune a
poller into a job it cannot do, the responsibility splits:

| lead | owner | mechanism |
| --- | --- | --- |
| ~1 hour before | the user's calendar | `VALARM` in the exported `.ics` |
| 24h before an interview | this app | `Notification`, config `interview_reminder_hours` |
| 48h before an offer deadline | this app | `Notification`, config `offer_deadline_reminder_days` |

Both config values follow the existing `follow_up_days` pattern
(`config.py:189`): `int`, `ge=0`, `0` disables. Both are validated to be at
least one tick interval. `VALARM` fires natively, on the user's phone, with no
server involved — which is what calendars are for.

Dedupe reuses the existing episode key idiom from `services/reminders.py`, keyed
on `(event_id, occurred_at)` so a rescheduled event opens a new episode and a
dismissal stays dismissed until the date actually moves.

## Calendar export

Per-event `.ics` download, authenticated like every other route, plus a
"download all upcoming" covering the live pipeline. Generated on the fly — no
stored artifact, so no `artifact_path` involvement.

Per event: `SUMMARY` (`{kind} — {company}`), `DTSTART`/`DTEND` (from
`occurred_at` + `duration_minutes`; `VALUE=DATE` when `all_day`), `LOCATION` and
`URL` from `location_or_link`, `DESCRIPTION` from notes + interviewers +
platform, `UID` stable per event id (so re-import updates rather than
duplicates), and a `VALARM` at −1 hour for timed events.

A subscribable feed is deferred — see below.

## Surfaces

### Job detail → Tracking tab

`ApplicationEditor` is restructured, not duplicated: one **Application** section
whose *header* shows the derived status (click to override) and whose *body* is
the timeline — add-event button, chronological list, inline edit. Keeping the
existing dropdown alongside a new timeline would leave two widgets showing
overlapping truth with no stated precedence, which is how UIs rot.

The application-level `notes` `<input>` becomes a textarea, distinct from
per-event notes.

### `/applications` — new page

One row per application; events pivoted into columns. Read-only; click through
to the job to edit.

- Fixed columns per kind, except `technical_round`, whose column count **grows
  to the maximum observed** in the user's data (capped at 6) so a fifth round is
  never silently hidden. Past the cap, the overflow renders as `+N` in the last
  column — visible, never silent.
- `custom` events collapse into one `Other (n)` column.
- Every column is present in both CSVs regardless of the cap; the cap is a
  display concern only.
- Cells show the **date only**; modality, platform, result, and interviewers
  appear on hover. Otherwise the grid is forty columns wide and unreadable.
- Sortable; filterable by status and company.

### Exports

Two CSVs from the same pivot function:

- **wide** — one row per application, matching the grid.
- **long** — one row per event, for the user's own pivot tables.

### Dashboard

A **Next 7 days** card, reusing the existing `AttentionCard` / `ActionQueue`
idiom (`web/src/features/dashboard/`): upcoming interviews and offer deadlines,
chronological, click-through to the job. A forgotten interview is a
categorically worse failure than any missing chart, and the dashboard is the
first screen the user sees.

Overdue nudges ("you logged an interview 10 days ago and never recorded a
result") are **out** — a second reminder engine with its own staleness rules,
overlapping the notification bell, nagging in two places.

## Analytics

Four charts on the existing `/analytics` page, which currently holds two thin
cohort tables. All four are buildable with the installed `recharts@3.10`
(`Sankey`, `FunnelChart`, `Treemap`, `RadialBar` are all present in
`web/node_modules/recharts/types/chart/`) — **no new dependency**.

1. **Stage-flow Sankey.** Applications flowing left→right through stages, with
   drop-off branches peeling to `rejected` / `no_response` / `withdrawn` at each
   stage. Answers "where do I actually die?". Edge labels carry percentages,
   which subsumes a separate funnel chart.
2. **Cycle-time bars.** Median days between consecutive stages
   (submit → recruiter screen → OA → tech 1 → … → offer). The most actionable
   new number: it says whether day-12 silence is normal or terminal.
3. **Active-pipeline timeline.** One lane per live application, events as dots,
   a "today" line, upcoming interviews and deadlines to its right.
4. **Offer comparison.** Stacked bars of base / bonus / equity / signing per
   offer. Renders only when at least one offer exists.

Dropped: a standalone funnel chart (subsumed by 1) and a calendar activity
heatmap (attractive, but "days I was active" drives no decision).

`custom` events are excluded from 1 and 2 and labelled as such, so the numbers
stay honest.

### The small-sample rule

Job-search datasets are inherently small — this is the permanent condition, not
a phase to grow out of — so the honesty rule is structural rather than a tooltip
caveat. The existing `_rate()` (`tracking/analytics.py:16`) returns `0` for an
empty denominator, which reads as a real zero.

- **Counts are always shown.**
- **Rates are annotated `n=` always.**
- **Rates below n=10 render greyed**; below n=3 they are **suppressed
  entirely**, showing counts alone.

Confidence intervals are the statistically correct answer and the wrong product
answer; nobody reads them.

Charts get the `dataviz` skill treatment at implementation time for shared
palette and small-multiple consistency, rather than four independently styled
recharts components.

## API

Nested under the job, matching `PUT /jobs/{id}/application`:

| method | path | purpose |
| --- | --- | --- |
| `GET` | `/jobs/{id}/events` | timeline for one application |
| `POST` | `/jobs/{id}/events` | create |
| `PATCH` | `/jobs/{id}/events/{event_id}` | update |
| `DELETE` | `/jobs/{id}/events/{event_id}` | delete |
| `GET` | `/jobs/{id}/events/{event_id}.ics` | one VEVENT |
| `GET` | `/applications` | pivoted grid page |
| `GET` | `/applications.csv?shape=wide\|long` | export |
| `GET` | `/applications/upcoming.ics` | all upcoming events |
| `GET` | `/analytics/timeline` | data for charts 1–4 |

`GET /analytics` is unchanged; the new charts read a new endpoint so the
existing cohort tables keep working untouched.

## Testing

TDD, layered as the artifact-deletion work was: storage → repository → service →
routes → web. Specifically pinned:

- `has_progress` in **both** directions — empty `ready` row deletes; row with
  one event refuses. Plus `progressed_job_ids` agreeing with `has_progress` for
  the same fixtures.
- Progression-versus-terminal status transitions, including `offer → rejected`.
- Migration idempotence: running `ensure_application_submitted_events` twice
  produces one event.
- `.ics` output parsed back, asserting `DTSTART`/`DTEND`, `TZID`, all-day form,
  and `VALARM`.
- Small-sample suppression at the n=3 and n=10 boundaries.
- Reminders firing for a user with **no** Gmail token.

## Implementation phasing

This is too large for one undifferentiated plan. Three phases, each
independently shippable and green on its own:

**Phase 1 — the record.** `ApplicationEvent` table, vocabularies, both
migrations, the two invariant changes with their ADRs, event CRUD routes, and
the restructured Tracking tab. Ships a usable timeline. Nothing downstream is
designable without it, and both invariant changes land here so the delete gate
and status rules are settled before anything reads them.

**Phase 2 — the clock.** Reminder decoupling from Gmail (fixing the latent
bug), the hourly tick, the two config values, `.ics` export, and the dashboard
**Next 7 days** card. Ships the "don't miss an interview" value, which is the
highest value-per-line in the feature.

**Phase 3 — the retrospective.** `/applications` grid, both CSV exports,
`GET /analytics/timeline`, and the four charts with the small-sample rule.
Needs real data to be worth looking at, so it benefits from shipping last.

## Deferred, with reasons

| deferred | why | unblocked by |
| --- | --- | --- |
| **Subscribable `webcal://` feed** | An unauthenticated, permanently live URL exposing every company applied to and every interview date. Calendar clients send no session cookie, so it needs a per-user capability token, a revoke path, and a rate limit — a trust-boundary addition deserving its own design pass under ADR-0008. | Nothing here; `.ics` per-event delivers the goal. |
| **Gmail proposing events** | The Gmail path is deliberately deterministic. Datetime extraction from email prose is hard — relative dates, timezone-less times, reschedule threads superseding earlier ones, "let's find a time" with no time. A wrong block on the calendar is worse than no block. | The `source` field is already `manual \| migration \| gmail`; no schema change needed later. |
| **Reflections seeding mock interviews** | Genuinely valuable (`interview/store.py:330` builds session context), but it is a prompt-surface change to a tested agent. | `reflection` is stored and readable from day one. |
| **Reflections feeding profile facts** | **Never.** Self-assessment is not resume evidence; the fact-check gate exists to keep exactly this out. | — |
| **Level on the offer** | Belongs on the job, not the offer, and L4 ≠ E4 ≠ SDE-II is a normalization rabbit hole. | — |
| **Inline editing in the `/applications` grid** | Editing a sparse pivoted grid is high UI risk for little gain over click-through. | — |

## Invariants touched

Two, both requiring an ADR:

1. **Application status ordering** — replaces the flat high-water mark with
   progression-versus-terminal. Amends `tracking/CLAUDE.md`.
2. **`has_progress`** — an `Application` row alone no longer constitutes
   progress. Amends the "archive, delete, prune" invariant in the root
   `CLAUDE.md` and `tracking/CLAUDE.md`.

## Research

The stage vocabulary follows the standard 2026 SWE funnel: recruiter screen
(15–45 min) → online assessment (predominantly new-grad/L3; L4+ frequently
skip) → technical phone screen (1–2 rounds) → onsite loop of 3–5 rounds (DSA ×2,
low-level design, system design for experienced roles, behavioural / hiring
manager) → hiring committee → offer. Three to six weeks from first call to
written offer at large companies; under a week at startups. Offer deadlines run
2–7 business days, 24–72 hours being common, extensions usually negotiable up to
about a week — which is why `offer_deadline` is a first-class dated event with
its own reminder rather than a note.

- [Levelop — The Complete Software Engineer Interview Process in 2026](https://levelop.dev/blog/the-complete-software-engineer-interview-process-in-2026-what-to-expect-at-every)
- [Prepfully — Software Engineer Interview Rubric 2026](https://prepfully.com/interview-guides/software-engineer-interview-rubric-2026)
- [TechPrep — Google's Interview Process (2026)](https://www.techprep.app/blog/google-interview-process)
- [Somehow Manage — How to Negotiate an Offer Deadline Extension](https://somehowmanage.com/2022/01/17/how-to-negotiate-an-offer-deadline-extension/)
- [LockedIn AI — Accept Job Offer: How Long to Respond](https://www.lockedinai.com/blog/how-long-to-accept-job-offer-candidate-guide)
