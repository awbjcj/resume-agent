# Discovery pipeline developer reference

Migrated from the project root `CLAUDE.md` (2026-08-15, CLAUDE.md split) — loads only when working under `src/resume_tailor_harness/discovery/`.

### Source priority — upgrade, not drop

When two sources see the same job, the canonical source wins over an aggregator.
The existing `Job` row is **mutated in place** (same id); user progress — status,
`Application`, `ResumeVersion`, `CoverLetter` — is never touched.

| Tier          | Sources                                                                                                                                                                                      |
| ------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Canonical** | `greenhouse`, `lever`, `ashby`, `workday`, `tesla`, `google`, `smartrecruiters`, `workable`, `recruitee`, `personio`, `breezy`, `jazzhr`, `bamboohr`, `companies`, `scrape`, `url`, `manual` |
| **Fallback**  | `adzuna`, `remoteok`, `linkedin`                                                                                                                                                             |

Equal-tier re-pulls are no-ops (first-seen-wins). Once a job's status has
advanced past `raw`, only the apply `url` is upgraded; `jd_text` is frozen so a
resume already tailored to the old text is not silently re-based.

---

## Design notes

- **Discovery + tailor LLM calls run concurrently** via asyncio. Each phase keeps a sync public
  signature and runs `asyncio.run(gather_isolated(...))` internally: load rows → fan out the pure
  async LLM siblings (`aextract_job_criteria`, `ascore_fit`, `ajudge_relevance`, `arun_tailor_review`)
  → apply to the Session + commit on the single event-loop thread (no locks). One global
  `asyncio.Semaphore(Settings.llm_concurrency)` per `asyncio.run` caps in-flight calls
  (`llm_concurrency` is validated `>= 1`); it is acquired **only** inside `llm_runner.acall`
  (the leaf), so nested tailor fan-out (jobs × panel) can't deadlock. Retry/backoff is agno's
  per-agent config via `retry_kwargs()`; retries live in `AgentRunner` behind the `is_transient`
  predicate (rate-limit/timeout/5xx retry with exponential backoff; auth/schema/parse failures
  surface after one call); agno's own retry is disabled via `retry_kwargs() == {"retries": 0}`.
  A job whose LLM work fails is skipped (left in its prior status) and retried next run.
- **Industry normalization is scoped.** `_normalize_job_industries` walks only the
  just-extracted batch plus rows with a pending `_industry_candidate` or legacy SIC keys --
  never the whole table.

> ATS/job-board connector internals (detection, ATS readers, companies dispatch, Workday pagination, Tesla/Google portals, pooled HTTP, relevance gates) live in `src/resume_tailor_harness/discovery/connectors/CLAUDE.md`.
