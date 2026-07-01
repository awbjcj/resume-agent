# Resume Agent — Developer Reference

## Commands

```bash
# Test (offline — no API key, no network needed)
.venv/Scripts/python.exe -m pytest

# Lint
ruff check
```

All agent calls and the Playwright browser are faked in tests. Connector backends
are tested against fixture JSON payloads, not live endpoints.

---

## API layer (`api/`)

The FastAPI app is a thin adapter over the domain code, alongside the CLI — both
call the same `services/` use-case layer
(`discovery`, `tailoring`, `cover_letters`, `rendering`, `board`). No business
logic lives in routers. Start it with `resume-agent serve`; `create_app(...)` in
`api/app.py` is the factory (lifespan runs `init_db`, stores the engine on
`app.state`).

- **Pydantic schemas are the contract source of truth.** `CamelModel`
  (`api/schemas/base.py`) sets `alias_generator=to_camel` + `from_attributes`, so
  the wire format is **camelCase** while Python stays snake_case, and DTO→schema is
  a `model_validate(row)` projection (the schema whitelists fields off the richer
  query DTO). FastAPI emits OpenAPI → `scripts/export_openapi.py` writes
  `contracts/openapi.json` → `openapi-typescript` writes `contracts/ts/api.ts`.
  Regenerate with `bash scripts/gen_ts_client.sh`; `tests/api/test_openapi_contract.py`
  is a drift gate.
- **Long ops = a Run + SSE.** `pull`/`discover`/`tailor`/`cover-letters`/add-from-URL
  return `202` with a run record; work runs in a threadpool via `RunManager`
  (`api/runs/manager.py`), keyed by `run_id`, reusing `ProgressReporter` under
  `data/runs/`. **Each worker opens its OWN DB session** bound to the app engine —
  never the request session (not thread-safe). Clients watch `GET /api/runs/{id}/events`
  (sse-starlette) or poll `GET /api/runs/{id}`.
- **Errors** use one envelope `{ "error": { code, message, details? } }` via
  `ApiException` + handlers in `api/errors.py`.
- **Auth/CORS:** optional static bearer via `Settings.api_token` (guards every
  route except `/api/health`; off when unset); `Settings.cors_origins` allowlist.
- **In-memory sqlite tests** need a shared connection: `make_engine` gives
  `sqlite://` a `StaticPool` + `check_same_thread=False` so the request threadpool
  sees the schema the lifespan thread created.
- **Deferred (not exposed over HTTP):** Gmail sync, profile build, LinkedIn scrape.

---

## LLM providers (`llm_runner.py`)

Every LLM agent is built through one seam — `build_model(model_id)` in
`llm_runner.py` — which is the **only** place that knows about provider SDKs. No
builder imports a concrete agno model class directly.

- **Provider-prefixed model ids.** `split_provider` reads a `provider:model`
  prefix: `openai:` / `gemini:` / `deepseek:` route to that provider; a bare id
  (or an unknown prefix, e.g. a Workday `tenant:site`) defaults to **Anthropic**,
  so legacy Claude ids pass through unchanged.
- **Per-provider keys.** `resolve_api_key(model_id)` maps the resolved provider to
  its `Settings` field (`anthropic_api_key` / `openai_api_key` / `gemini_api_key`
  / `deepseek_api_key`). `relevance.py`'s "no key → return `None`" guard uses it,
  so it is provider-aware.
- **Lazy SDK imports.** `build_model` imports the agno provider class *inside* its
  branch, so a Claude-only run never imports `openai` or `google-genai`, and a
  missing optional SDK fails only when that provider is actually selected.
- **Tiers unchanged.** `model_for_tier` still maps `cheap`/`mid`/`premium` →
  `Settings.{cheap,mid,premium}_model`; the prefix lives inside those ids.
- **Dependency note.** agno 2.6.x's Gemini import needs `google-genai`'s
  `step_delta` submodule, renamed to `stepdelta` in 2.9.0 — `pyproject.toml`
  caps it at `<2.9.0`. DeepSeek and OpenAI both ride the `openai` SDK.

To add a provider: extend `PROVIDERS`, add its key to `Settings`, and add a branch
to `build_model` with a lazy import. Nothing else changes.

---

## Core invariants (never break these)

### Fact-lock
Every bullet on a tailored resume must trace back to a fact in
`data/profile/facts.json`. The `fact-check` reviewer in `review.yaml` is a
**hard gate** (not scored) — any unsupported claim fails the round. Agents
rewrite and reframe; they never invent.

### Source priority — upgrade, not drop
When two sources see the same job, the canonical source wins over an aggregator.
The existing `Job` row is **mutated in place** (same id); user progress — status,
`Application`, `ResumeVersion`, `CoverLetter` — is never touched.

| Tier | Sources |
| --- | --- |
| **Canonical** | `greenhouse`, `lever`, `ashby`, `workday`, `tesla`, `google`, `smartrecruiters`, `workable`, `recruitee`, `personio`, `breezy`, `jazzhr`, `bamboohr`, `companies`, `scrape`, `url`, `manual` |
| **Fallback** | `adzuna`, `remoteok`, `linkedin` |

Equal-tier re-pulls are no-ops (first-seen-wins). Once a job's status has
advanced past `raw`, only the apply `url` is upgraded; `jd_text` is frozen so a
resume already tailored to the old text is not silently re-based.

### Archive, delete, prune
`Job.archived_at` (orthogonal to `status`) soft-hides a job; every view filters
`archived_at IS NULL` — including the dedupe lookup (`find_existing`), so an archived
(trash-binned) duplicate never blocks re-ingesting the same job as a fresh active row.
`has_progress(session, job_id)` — status in
{approved, tailored, rendered} OR any Application/ResumeVersion/CoverLetter — is
the single gate for irreversible paths. `delete_job` refuses jobs with progress and
cascades incidental children in FK-safe order otherwise. `prune_run` (config:
`config/prune.yaml`) archives rejected/low-fit/stale zero-progress jobs, reports
primary reason counts, then hard-deletes archived zero-progress jobs older than
`retention_days`. Surfaced via the web Triage page and
`resume-agent prune [--dry-run]`.

---

## ATS detection flow (`detect.py`)

`detect_ats(url)` resolves in order — stop at the first match:

1. **Singleton host match** — `tesla.com/careers` → `AtsTarget("tesla")`;
   `careers.google.com` → `AtsTarget("google")`. No token; the host is the
   identity. Checked before L1/L2.
2. **L1 URL pattern** — host + path directly reveals ATS and board token
   (Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee, Personio,
   Breezy, JazzHR, BambooHR, and the Workday triple from
   `{tenant}.{dc}.myworkdayjobs.com/{site}`).
3. **L2 HTML sniff** — fetches the page, scans for embedded ATS markers
   (Greenhouse embed `?for=`, Lever/Ashby slugs, Workday full URL in HTML).

`AtsTarget` fields: `ats`, `token` (single-slug ATS account), `country` (Personio
host suffix), `tenant` +
`datacenter` + `site` (Workday triple). Tesla/Google carry only `ats`.

---

## Companies connector dispatch (`companies.py`)

`CompaniesConnector.fetch` delegates to the `harvest` seam: for each URL in
`self.urls` it calls `detect_ats`, looks up the backend in `_BACKENDS`, and calls
`backend(target, search, limit, skip_seen)`. Any URL that fails detection or whose backend
raises `httpx.HTTPError` / a parse error is recorded on the returned
`FetchResult.failures` (url → reason) — it never aborts the run. The relevance
gate `harvest` runs over the union is the backstop for backends that don't filter
server-side.

To add a new backend: write `fetch_<name>(target, search, limit, skip_seen=None) -> list[RawJob]`
in a new module, add detection logic to `detect.py`, register in `_BACKENDS`.

---

## Workday N+1 pattern (`workday.py`)

Workday boards can have thousands of global listings — pulling all then gating
locally is infeasible.

1. **POST** `…/wday/cxs/{tenant}/{site}/jobs` with `{"searchText": ..., "limit": 20, "offset": N}` — paginated list, title + location only.
2. **`title_relevance_gate`** prunes the list _before_ any detail fetch.
3. **GET** `…/wday/cxs/{tenant}/{site}{externalPath}` for each survivor → `jobPostingInfo.jobDescription` (HTML → text via `html_to_text`).

Safety ceiling: `_MAX_OFFSET = 1000` (≤51 pages) even if the tenant ignores
`searchText`. Keep `search.yaml` role anchors tight — the title-gate's
aggressiveness determines how many detail fetches are issued.

---

## Relevance gates (`text.py`)

| Function | When used |
| --- | --- |
| `title_relevance_gate` | Before JD text is available (Workday list rows, Tesla listing state) |
| `relevance_gate` | Full gate on title + JD; falls back to keyword search when no `role_anchors` are configured |
| `primary_search_term` | Picks the strongest term to send as `searchText` to Workday / Google; falls back to `role_anchors` if `titles` and `keywords` are empty |
| `primary_location` | Picks the first configured location for ATS endpoints such as Lever that accept a free-form location filter |

---

## Hot paths (most-edited files)

| Path | Role |
| --- | --- |
| `src/resume_agent/llm_runner.py` | `build_model` provider seam + `AgentRunner` adapter |
| `src/resume_agent/discovery/connectors/detect.py` | ATS detection (singleton → L1 → L2) |
| `src/resume_agent/discovery/connectors/companies.py` | Dispatch table + per-URL fail isolation |
| `src/resume_agent/discovery/scraper/dashboard.py` | Opt-in learned-recipe browser replay; cache in `data/scraper_recipes/` |
| `src/resume_agent/discovery/connectors/workday.py` | Workday CXS list → gate → detail |
| `src/resume_agent/discovery/connectors/tesla.py` | Tesla bespoke JSON portal |
| `src/resume_agent/discovery/connectors/google.py` | Google Careers JSON API |
| `src/resume_agent/discovery/connectors/text.py` | Relevance gates + `html_to_text` |
| `src/resume_agent/discovery/connectors/runner.py` | Pull orchestration, `+N added, N upgraded` telemetry |
| `src/resume_agent/concurrency.py` | `gather_isolated` — ordered, error-isolated async fan-out |
| `src/resume_agent/discovery/ingest.py` | `save_or_upgrade`, source-priority logic |
| `src/resume_agent/tracking/dedup.py` | `compute_dedup_key` — `company|normalized_title` |
| `tests/test_discovery_ingest.py` | Ingest + dedup + priority tests |

---

## Known design notes

- **`dedup_key` drops location.** `compute_dedup_key` is `normalize(company)|normalize_title(title)`.
  Multi-location same-title Workday reqs (e.g. "Software Engineer" in Austin vs. Detroit at GM)
  collapse to one job. Flagged as a follow-up micro-spec — fix is adding location to the key or a
  location-aware secondary check.
- **Workday `appliedFacets` not used.** v1 shapes requests with `searchText` only. Location/category
  facet IDs are tenant-specific (require a separate facets call) and are a later refinement.
- **Tesla/Google endpoints are reverse-engineered.** They have no public API contract and could change
  without notice. Each is isolated to its own module behind `_BACKENDS`; a parse failure records to
  `.failures` and never aborts the pull.
- **Adzuna enrichment needs a real (non-headless) browser.** The API returns only a truncated snippet,
  and `redirect_url` is a bot-gated `/land/ad/` click-tracker — bare `httpx` gets `403` and *headless*
  Chromium is challenged ("suspicious behaviour"); only a non-headless browser follows the redirect to
  the employer/aggregator posting (Dice, Greenhouse, …). So `AdzunaConnector.fetch` (when
  `enrich_details=True`, the default) relevance-gates the snippets, then `enrich_adzuna_jobs` calls
  `browser.render_pages` to drive **one shared visible browser context** over every survivor's
  `redirect_url` (distinct ads are safe; re-clicking the *same* ad boomerangs to a search page),
  captures each post-redirect `final_url`, and extracts the JD via `enrich_adzuna_job(job, page)`
  (LinkedIn/Greenhouse branches, else JSON-LD → description selectors → whole-page markdown, taking the
  **first** materially-richer candidate in specificity order, with logo `![](…)` images stripped).
  Any render/extract failure leaves the snippet intact and is recorded in `.failures`. Enrichment is
  un-exercised by the offline suite (the browser is faked); a pull is slower and pops a window.
- **Discovery + tailor LLM calls run concurrently** via asyncio. Each phase keeps a sync public
  signature and runs `asyncio.run(gather_isolated(...))` internally: load rows → fan out the pure
  async LLM siblings (`aextract_job_criteria`, `ascore_fit`, `ajudge_relevance`, `arun_tailor_review`)
  → apply to the Session + commit on the single event-loop thread (no locks). One global
  `asyncio.Semaphore(Settings.llm_concurrency)` per `asyncio.run` caps in-flight calls
  (`llm_concurrency` is validated `>= 1`); it is acquired **only** inside `llm_runner.acall`
  (the leaf), so nested tailor fan-out (jobs × panel) can't deadlock. Retry/backoff is agno's
  per-agent config via `retry_kwargs()` (`exponential_backoff=True`); note it retries bare
  `Exception`, so a parse failure costs `llm_retries` extra calls — kept low (default 2).
  A job whose LLM work fails is skipped (left in its prior status) and retried next run.
