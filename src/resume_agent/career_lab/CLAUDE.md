# Career Lab developer reference

Migrated from the project root `CLAUDE.md` (2026-08-15, CLAUDE.md split) — loads only when working under `src/resume_agent/career_lab/`.

- **A Career Lab thread's `job_id` is an index, not its context.** A thread may
  be anchored to a job (started from the job modal's Career Lab tab) or
  un-anchored (started from the Career Lab page). `CareerLabSession.job_id`
  records which, so a job's own surfaces can list its threads
  (`GET /api/career-lab/sessions?jobId=`) — but what the agent actually reads
  stays per-turn in `CareerLabTurnRecord.context_refs`, which a roaming
  conversation may legitimately point at a different job on any later turn. Do
  not read the session's `job_id` as the prompt's job.
  **One active thread per job, with `job_id=None` as its own bucket.** The rule
  is enforced in three places that must agree on scope, each buying something
  the others cannot: `store.create_session` under `store.lock()` is the atomic
  authority; the router pre-flights it because work runs through `launch`, where
  a service `ValueError` would surface as a _failed run_ rather than a 409; and
  `run_start_turn` re-checks before paying for router/persona/formatter calls.
  The start's `launch` singleton key is scoped to the same job. Two consequences
  are easy to break: a surface may not gate "start a new thread" on _any_ active
  thread (that hid the Career Lab page's New-session button as soon as any job
  thread opened), and the CLI's `--job-id` must resume _that job's_ thread —
  "whatever is open" was exact only while one thread could exist at a time.
  Career Lab threads cascade on job delete alongside interview sessions and
  never gate it (`has_progress` untouched).
  **The listing is ordered open-threads-first, then newest** (`_ordered_for_listing`),
  which is what lets a job's tab decide whether to offer Start from page 1
  alone — the substrate lists oldest-first, so an open thread could sit past the
  page boundary and the tab offered a Start the API then 409'd. Two stable
  passes, not one composite key: the components sort in opposite directions.
  `jobCompany`/`jobTitle` on the summary are resolved **live** in one batched
  query per page (never per row), because Career Lab deliberately freezes no job
  snapshot the way `InterviewContext` does; a thread whose job is gone simply
  has no label.
