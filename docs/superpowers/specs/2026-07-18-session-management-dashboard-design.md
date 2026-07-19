# Session Management + Dashboard Upgrade — Design

**Date:** 2026-07-18
**Status:** Approved for planning

## Goal

Let the user manage past Mock Interview and Profile Coach sessions
(resume in-progress, review, archive, delete), run several interviews for
different jobs concurrently from a dedicated Interview hub page, and upgrade the
dashboard to show in-progress sessions plus durable, user-clearable error
records for failed runs and failing sources.

## Decisions (settled during brainstorming)

1. **Concurrency:** one active interview session **per job**; unlimited across
   jobs. Coach stays single-active globally.
2. **Resume:** only `status="active"` sessions can be resumed (they already
   survive restarts as files). Ended sessions (debriefed / recapped) are
   read-only records — never reopened, so a debrief always reflects its full
   transcript.
3. **"Profile build agent" = Profile Coach** (the `/coach` chat), not the corpus
   build pipeline.
4. **Error-record scope:** failed background runs (`state="error"`) and
   per-source fetch failures from pull reports. Per-job LLM skips are out of
   scope (they self-retry).
5. **Dashboard scope:** sessions-in-progress panel + error panel only. No new
   analytics (activity trends, source health strip, practice stats deferred).
6. **Architecture:** keep the file-based session stores; add a new
   `error_records` table to the workspace DB. No session-storage migration.

## 1. Session lifecycle (stores)

### Interview store (`src/resume_agent/interview/store.py`)

- `InterviewSession` gains `archived_at: str | None = None` — a soft-hide flag
  orthogonal to `status`, mirroring `Job.archived_at`.
- The global single-active guard in `create_session` becomes per-job:
  `active_session_for_job(interview_dir, job_id)` replaces `active_session()`
  in the guard. Starting an interview for a job with an active session raises a
  conflict; other jobs' active sessions never block.
- New delta-under-lock mutations:
  - `archive_session` / `unarchive_session` — **ended sessions only**. Active
    sessions cannot be archived (resume or delete them instead).
  - `delete_session` — any session, permanent file removal. Deleting an active
    session is the "abandon without debrief" path.
- `list_sessions` gains `include_archived: bool = False`; default views hide
  archived rows.
- Run singleton key changes from global `"mock-interview"` to
  `f"mock-interview:{session_id}"`: one in-flight turn per session instead of
  per app, which is what enables parallel interviews. The global
  `llm_concurrency` semaphore still bounds total LLM load.

### Coach store (`src/resume_agent/profile/coach_store.py`)

- Same `archived_at` field and archive/unarchive/delete mutations, same
  ended-only archive rule.
- Stays single-active globally.
- Deleting a coach session removes only the transcript record; saved notes are
  corpus documents and are never touched.

Job deletion continues to delete that job's interview sessions (unchanged);
coach sessions are job-agnostic. No automatic retention for sessions — they are
user-managed records. `has_progress` is untouched: sessions never gate job
deletion.

## 2. API surface

Routers stay thin adapters over `services/`; schemas in `api/schemas/`
(camelCase wire). Contract regenerated via `bash scripts/gen_ts_client.sh`;
`tests/api/test_openapi_contract.py` is the drift gate. Error mapping keeps the
`ApiException` envelope and the existing 404/409/422 conventions.

### Interview (`api/routers/interview.py`)

- `POST /api/interview/sessions` — guard becomes
  `active_session_for_job(job_id)`; conflict code `SESSION_ACTIVE_FOR_JOB` with
  the existing session id in `details` so the UI can offer "resume instead".
- `GET /api/interview/sessions` — adds `includeArchived` (default false) and
  `status` query filters. Summary rows add `archivedAt`, `endedAt`, and
  `progress` so list UIs need no per-session detail fetches.
- `POST /api/interview/sessions/{id}/archive` and `/unarchive` — 409 when the
  session is active (archive) or not archived (unarchive).
- `DELETE /api/interview/sessions/{id}` — permanent; 404 unknown.
- Turn/end endpoints unchanged except the per-session singleton key.

### Coach (`api/routers/coach.py`)

- `POST /api/coach/sessions/{id}/archive`, `/unarchive`,
  `DELETE /api/coach/sessions/{id}` — same semantics.
- `GET /api/coach/sessions` gains the same filters. Start-session keeps its
  existing single-active 409.

### Errors (new `api/routers/errors.py` + `services/errors.py`)

- `GET /api/errors?status=open` — newest first; rows carry `kind`,
  `sourceLabel`, `runId`, `message`, `count`, `firstSeenAt`, `lastSeenAt`,
  `status`.
- `POST /api/errors/{id}/dismiss`, `POST /api/errors/{id}/resolve` — distinct
  terminal statuses ("ignored" vs "fixed"); both leave the default open view.
- `POST /api/errors/dismiss-all` — bulk-dismiss all open records ("clear").
- `GET /api/dashboard` extended with `openErrorCount` and in-progress session
  summaries so the dashboard stays a single fetch.

## 3. Error records: data model and writers

### Table (workspace DB — per-user by construction)

```
error_records
  id            int PK
  kind          "run" | "source"
  source_label  str      # run kind ("pull", "tailor", …) or source unit ("workday:acme", …)
  run_id        str|null # last run that produced it
  message       str
  details       JSON|null
  status        "open" | "dismissed" | "resolved"
  count         int
  first_seen_at / last_seen_at / updated_at
```

### Dedup

Before insert, the service looks for an **open** record with the same
`(kind, source_label)`; if found it bumps `count` and refreshes `last_seen_at`,
`message`, `run_id`. Dismissed/resolved records never absorb new failures — a
source failing again after resolution creates a fresh open record.

### Writers (two, at existing failure choke points)

1. **Run failures:** `RunManager`'s worker `except Exception` path gains a
   callback hook injected at app startup (like the reporter). The hook writes a
   `kind="run"` record, opening **its own DB session** on the app engine per the
   threading invariant. `recover_interrupted` writes through the same hook.
2. **Per-source fetch failures:** the pull service, where the runner report's
   `failures: {connector: {url: reason}}` is assembled, writes one
   `kind="source"` record per failing unit. Connectors stay pure.

CLI runs do not write error records (failures already print inline).

### Retention

Dismissed/resolved records older than 30 days are pruned opportunistically on
error-list reads. Open records live until acted on.

## 4. Web UI

### Interview hub (`/interview`)

- **Left rail — session list**, grouped *In progress* (job title/company, stage
  badge, "question N of M", started-ago) then *Completed* (debrief score
  summary), with an "Archived" toggle revealing archived rows. Kebab actions:
  Resume/Review (open), Archive/Unarchive (ended only), Delete (confirm dialog;
  warns about abandoning when the session is active).
- **"New interview"** opens the existing `InterviewSetupDialog` extended with a
  job picker: jobs having ≥1 tailored `ResumeVersion`, minus jobs with an
  active session (those show "resume existing").
- **Main pane** — the existing chat/debrief view for the selected session;
  deep-linking stays `?session=`.

### JobModal `InterviewTab`

Per-job entry point: that job's sessions only (existing `jobId` filter), same
actions, linking into `/interview?session=…`. `ActiveInterviewBanner` semantics
change from "an interview is active" (global) to "this job has an active
interview".

### Coach page (`/coach`)

History drawer (sheet): resume the active session, review ended ones read-only
(transcript + recap + saved-note markers), archive/delete.

### Dashboard

Two new cards:

- **In progress** — active interview sessions (company/title, progress,
  started-ago → resume link) and the active coach session, from the extended
  `/api/dashboard` fetch. RecentRuns stays as is for background runs.
- **Attention needed** — open error records from `GET /api/errors?status=open`
  (the dashboard summary carries only `openErrorCount` for the badge/empty
  state): message, source label, "seen N×",
  last-seen-ago; per-row Dismiss/Resolve; "Clear all" header action. Empty
  state collapses to a quiet "no open errors" line.

## 5. Testing

Offline throughout (no API key, no network):

- **Store tests:** archive/delete/per-job-active semantics on tmp-dir JSON
  fixtures, matching existing store-test style.
- **Service tests:** error-record dedup, reopen-after-resolve, and prune
  against in-memory SQLite (`StaticPool` engine).
- **Router tests:** management endpoints through the FastAPI test app; contract
  regenerated and gated by `test_openapi_contract.py`.
- **RunManager hook test:** a failing run writes exactly one record; worker DB
  sessions are per-thread.
- **Web (vitest):** sessions rail, coach history sheet, both dashboard cards,
  updated setup dialog — following existing `*.test.tsx` fixture patterns.

## Out of scope

- Reopening ended sessions; multiple active sessions for the same job.
- Concurrent coach sessions.
- Dashboard analytics (activity trends, source-health strip, practice stats).
- Error records for per-job LLM skips or CLI runs.
- Session-storage migration to SQLite.
