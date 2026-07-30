# Resume Agent — Developer Reference

## Branching

`dev` is the integration branch — all feature work branches off `dev` and PRs back
into it; `main` is protected (PR + passing checks required, no direct
pushes/force-pushes) and is the only branch Railway deploys from. Promote `dev`
→ `main` via PR when a batch of work is ready to ship.

CI is split by branch so `dev` gets fast feedback and `main` gets the full
gate before a deploy-triggering merge: `.github/workflows/_reusable-ci.yml`
holds the actual jobs (`python-quality`, `web-quality`, `security-audit`)
behind a `full` input; `.github/workflows/ci-dev.yml` calls it with
`full: false` (lint + test only) on pushes/PRs to `dev`, and
`.github/workflows/ci-main.yml` calls it with `full: true` (adds the web
production build and the pip-audit/npm-audit dependency scan) on
pushes/PRs to `main`. `.github/workflows/codeql.yml.disabled` is a
fully-commented placeholder — a fully-commented file with a live `.yml`
extension still gets parsed (and fails) as an invalid workflow by GitHub
Actions, so it's kept as `.disabled` until the repo goes public: rename it
back to `.yml` and uncomment it then.

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
  (sse-starlette) or poll `GET /api/runs/{id}`. Every router starts its run through
  the **launch seam** (`api/runs/launch.py`): `launch()` submits + maps the three
  launch-time errors onto the API envelope (singleton→409, reset→409, quota→429),
  and `session_work()` owns the worker-opens-its-own-session rule.
- **Errors** use one envelope `{ "error": { code, message, details? } }` via
  `ApiException` + handlers in `api/errors.py`.
- **Auth/CORS:** optional static bearer via `Settings.api_token` (guards every
  route except `/api/health`; off when unset); `Settings.cors_origins` allowlist.
- **In-memory sqlite tests** need a shared connection: `make_engine` gives
  `sqlite://` a `StaticPool` + `check_same_thread=False` so the request threadpool
  sees the schema the lifespan thread created.
- **Board filters are declared once.** `tracking/board_query.py` owns the shared
  shortlist/pipeline/triage selection, sorting, paging, and facet expressions;
  `board_filter_query(default_sort)` only maps the shared HTTP query surface
  into that contract. Triage's extra `archived` flag stays endpoint-local via
  `dataclasses.replace`.

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
- **Lazy SDK imports.** `build_model` imports the agno provider class _inside_ its
  branch, so a Claude-only run never imports `openai` or `google-genai`, and a
  missing optional SDK fails only when that provider is actually selected.
- **Tiers unchanged.** `model_for_tier` still maps `cheap`/`mid`/`premium` →
  `Settings.{cheap,mid,premium}_model`; the prefix lives inside those ids.
- **Dependency note.** agno 2.6.x's Gemini import needs `google-genai`'s
  `step_delta` submodule, renamed to `stepdelta` in 2.9.0 — `pyproject.toml`
  caps it at `<2.9.0`. DeepSeek and OpenAI both ride the `openai` SDK.
- **Gemini thinking is generation-specific — never send `thinking_budget` to
  Gemini 3.** Gemini treats an unset thinking config as "provider decides"
  (unbounded automatic budget), so non-reasoning agents must bound it. But
  Gemini 3 replaced `thinking_budget` with `thinking_level` and **rejects the
  budget outright**: `thinking_budget=0` fails the whole request with `400
INVALID_ARGUMENT` before generating anything, and agno then hands back the
  error body as a plain `str` — surfacing as "Expected ResumeContent, got str"
  rather than as an HTTP error. `build_model` therefore bounds Gemini 3 with
  `thinking_level` (`low` when not reasoning, `high` when reasoning) and keeps
  `thinking_budget=0` only for pre-3 ids. Verified live against
  `gemini-3.6-flash`: `thinking_level="low"` reports no thought tokens;
  `thinking_budget=0` is a hard 400.
- **Anthropic has the same "unset means provider decides" trap, and it is
  generation-specific.** Omitting `thinking` runs **adaptive** on Sonnet 5 and
  Opus 5, and runs **without** thinking on Opus 4.8/4.7 and older — so leaving
  it unset silently bought thinking on every non-reasoning agent using the
  default `mid_model`. Because `max_tokens` caps thinking **plus** response
  text, that truncated large structured outputs into the same unparsed-`str`
  symptom as the Gemini bug. `_anthropic_thinking` therefore sends
  `{"type": "disabled"}` for non-reasoning 4.6+ ids (omitting it on pre-4.6,
  where unset already means off, and on Fable/Mythos, which reject a disabled
  config), and `_anthropic_max_tokens` replaces agno's 8192 default — clamped
  to the SDK's per-model non-streaming ceiling so a custom Opus 4/4.1 id
  cannot raise `ValueError`.
- **Claude capability gates read the model generation, never a substring.**
  `anthropic_version` parses `claude-<family>-<major>[-<minor>]` into a
  comparable tuple; pre-4 ids (`claude-3-5-haiku-…`) put the version first and
  deliberately return `None`, which is correct because every gated capability
  arrived with 4.6. Both adaptive thinking + `output_config.effort`
  (`provider_capabilities`) and the `web_search_20260209` tool variant
  (`anthropic_web_search_tool`) gate on `>= (4, 6)`. The old `"haiku" in
model` heuristic was right only for the catalog and 400'd for any pre-4.6 id
  entered through the tier picker's custom field; agno cannot catch this
  because its `NON_THINKING_MODELS` covers only Haiku 3 and 3.5.
- **Model-tier defaults live only on `Settings`.** `ModelsConfigDoc`
  (`api/schemas/secrets.py`) and `WizardState` (`setup/state.py`) derive theirs
  via `Settings.model_fields[...].default` instead of restating literals —
  which is how the wizard silently fell a generation behind (`claude-sonnet-4-6`
  vs `claude-sonnet-5`) while a test _named_ for that invariant kept passing by
  restating the literals too.
- **A structured-output call that returns `str` is diagnosed, not guessed.**
  agno leaves `RunOutput.content` as the raw `str` whenever it cannot parse a
  response into `output_schema`, which collapses truncation, refusal and a
  rejected request into one indistinguishable symptom. `expect_schema` in
  `llm_runner.py` is the single seam that raises `UnparsedAgentOutput` carrying
  model, provider, run status, token counts (including `reasoning`) and a head
  **and tail** preview — the tail is what shows a response was cut off. Use it
  at every `output_schema` call site instead of a bare `isinstance` check.
  Every such call site now does — cover letters, discovery (extract/fit/
  relevance), scraper recipes, URL ingest, profile extraction/inference/
  synthesis/projects, both scouts, and `sessions/turns.py` (so the coach and
  interview stacks inherit it) — so a bare `isinstance` guard on agent output
  is a regression. `UnparsedAgentOutput` subclasses `TypeError`, so adopting it
  never changes what a caller catches.

To add a provider: extend `PROVIDERS`, add its key to `Settings`, and add a branch
to `build_model` with a lazy import. Nothing else changes.

---

## Core invariants (never break these)

### Tenancy context (ADR-0003)

Multi-user state rides a `contextvars.ContextVar` holding the active
`UserContext` (`tenancy/context.py`). Its set-points are the API dependency,
`RunManager.submit` (which copies the caller context into its worker), and the
CLI callback (`--user`). The Workspace layout is named once: the relative-path
constants (`FACTS_PATH`, `SEARCH_PATH`, `CONNECTORS_PATH`, `REVIEW_PATH`,
`REVIEW_DEEP_PATH`, `TELEMETRY_PATH`, `SKILL_ALIASES_PATH`) live in
`tenancy/paths.py`, and `resolve_tenant_path` rebases them into the active
Workspace at the leaves — so callers pass defaults, not hand-threaded absolute paths. `get_settings()` returns effective request settings or
environment settings and must never be cached across requests. System tables
use separate SQLAlchemy metadata and never appear in workspace databases.
Session cookies and PATs resolve only to that context. Short-lived query tokens
are purpose-bound to SSE or selected downloads and are never accepted as
general API authorization. Limits use `NULL = system default` and `0 =
unlimited`; admins and calls made with a user's own provider key are exempt from
shared-key budget enforcement. Admin user deletion evicts open workspace
engines before a staged, rollback-safe removal.

### Public network trust boundary (ADR-0008)

A source-based threat model (`resume-agent-threat-model.md`,
`security_best_practices_report.md`, repo root) drove mandatory chokepoints
that every future user-influenced fetch, download, render, or archive import
must go through — see ADR-0008.

- **One egress gateway for user-influenced URLs.** `security/outbound.py`'s
  `fetch_public_text`/`resolve_public_url` is the only place allowed to make an
  HTTP(S) request to a URL a user supplied. It rejects non-`http(s)` schemes,
  embedded credentials, and any resolved address that is not globally routable
  (`ip_address(...).is_global`), then **pins the connection to the address it
  validated** while preserving the original `Host`/SNI — so a second,
  attacker-controlled DNS answer after the check (rebinding) can't steer the
  real request at a private address. Every redirect hop is revalidated the
  same way (`follow_redirects=False`, manual hop loop, capped at 5), and the
  response is capped by declared and actual byte count with a content-type
  allowlist (`text/*`, `application/xhtml+xml`). `profile/intake.py`,
  `discovery/url_ingest/fetch.py::fetch_static`, and
  `discovery/connectors/detect.py::_get_html` all call through it instead of a
  bare `httpx.get`; `services/sources.py` re-exports its resolver rather than
  keeping its own copy. A bare `httpx.get`/`.get(follow_redirects=True)` on a
  user-supplied URL anywhere in the codebase is a regression.
- **Tenant-confined artifact and render paths.** `tenancy/storage.py::artifact_path`
  is the only way a download route may turn a stored `pdf_path` into a
  `FileResponse` target. In multi-user mode (a tenancy context is active) it
  resolves the path beneath the tenant's own `output/` directory and raises
  `TenantPathError` for anything that resolves outside it — including an
  absolute path or `..` restored from an **imported** workspace archive, which
  is the actual attack: a tenant controls their own exported/re-imported
  `resume_versions`/`cover_letters` rows, so a sink that trusts stored paths
  verbatim lets an import plant a path pointing at another tenant's (or the
  host's) files. `api/routers/account.py::_validate_workspace_stage` normalizes
  every `pdf_path` in an imported database to a tenant-relative `output/...`
  value _before_ the atomic swap and refuses the import outright
  (`INVALID_ARCHIVE`) if a row can't be normalized; `resumes.py` and
  `cover_letters.py`'s download handlers resolve through `artifact_path` and
  treat `TenantPathError` as "not found," never as a 500. `render/service.py`
  and `cover_letter/render.py` write new artifacts under the active tenant's
  `context.paths.output_dir` rather than `RenderConfig.output_dir`, and
  `render/templates.py::template_path_for` refuses a legacy `template_path` in
  multi-user mode (`TemplateNotFoundError`) except the one literal legacy
  value that maps to the bundled `classic` template — a persisted or imported
  custom path can no longer select an arbitrary file. Local single-user mode
  (no tenancy context) keeps the historical explicit-path behavior for all of
  the above unchanged.
- **Callback and cookie decisions read configuration, never forwarded
  headers.** `api/public_url.py::public_url` builds the Google sign-in and
  Gmail OAuth redirect URIs from `Settings.app_base_url` when set, never from
  `X-Forwarded-Host`/`-Proto` — those are attacker-controlled unless a proxy
  strips them, and Railway's default Uvicorn setup does not declare a trusted
  proxy policy. `Settings.secure_cookies` forces the session cookie's `Secure`
  flag independent of `request.url.scheme` (also proxy-dependent);
  `Settings.allowed_hosts` wires `TrustedHostMiddleware`; `Settings.disable_api_docs`
  hides `/docs`, `/redoc`, and `/openapi.json`. The Dockerfile sets
  `SECURE_COOKIES=true` and `DISABLE_API_DOCS=true` by default and refuses to
  start unless `APP_BASE_URL` is an HTTPS origin — a production deploy
  additionally needs `ALLOWED_HOSTS` set (see `docs/deploy-railway.md`).
- **Archive extraction is resource-bounded, not just path-validated.**
  `services/backup.py::_extract_validated` streams `tarfile` members instead of
  materializing `getmembers()`, and rejects an archive during the scan (before
  `extractall`) once it exceeds `max_members` (10,000), any single member's
  size (512 MB), total expanded bytes (2 GB), or a >200:1 compression ratio
  against the compressed file's own size. `services/settings_bundle.py`'s
  bundle extractor now delegates to the same function with its own tighter
  bundle-sized limits instead of duplicating the size/member checks — one
  compression-bomb policy, two configured budgets.

### Registration modes and platform spend governance (ADR-0009)

`Settings.registration_mode` (`closed` / `invite` / `open`) is a business
decision independent of shared-key eligibility: open registration lets anyone
verify an email and create an account, but `User.shared_key_access` (default
`True` for invited users, `Settings.open_signup_shared_keys` — default
`False` — for open self-registered ones) decides whether that account may use
the _platform's_ LLM keys at all versus needing to bring its own. This closes
the Sybil-multiplication gap the threat model flagged: creating accounts
cheaply no longer creates shared-key spend by itself.

- `api/attempts.py::consume_global_signup` is an atomic (`BEGIN IMMEDIATE`),
  rolling-24h counter independent of per-email/per-IP attempt budgets, capping
  total verification emails sent per day (`Settings.global_daily_signup_limit`)
  regardless of how many distinct emails/IPs originate them.
- `tenancy/limits.py::enforce_agent_budget` runs before every LLM call
  (`llm_runner.py`'s `AgentRunner.run`/`arun`) and layers three checks: a
  non-admin account without `shared_key_access` is rejected outright when its
  resolved model has no per-user key configured (`context.own_key_providers`);
  otherwise the pre-existing per-user weekly token budget (`enforce_budget`,
  unchanged) still applies; and finally a platform-wide rolling-7-day sum (`global_weekly_usage`, summing `UsageEvent.weighted_total`
  where `own_key=False`) is checked against `Settings.global_weekly_token_budget`
  — the circuit breaker that caps total shared-key spend regardless of how
  many accounts exist. A user's own provider key is exempt from both the
  per-user and global shared-key budgets (same `own_key` accounting ADR-0003
  established).
- Open self-registration additionally seeds a lower per-account ceiling —
  `Settings.open_signup_weekly_token_budget`, `open_signup_max_active_jobs`,
  `open_signup_max_concurrent_runs` — onto the new `User` row, so an
  operator can run `registration_mode=open` with materially tighter defaults
  than an invited user gets, without a second code path.

The threat-model documents still record items **not yet implemented**: OAuth
state is not bound to the initiating browser or atomically consumed
(browser-binding, not just the existing HMAC), there is no explicit CSRF
token/Origin check for cookie-authenticated mutations, Typst/document
parsing/transcription still run in the API process rather than an isolated
worker, user provider keys are plaintext in `secrets.env` rather than
envelope-encrypted, and there is no dedicated security audit-event stream.
Check `resume-agent-threat-model.md` and `security_best_practices_report.md`
before assuming a related gap is already closed.

### Fact-lock

Every bullet on a tailored resume must trace back to a fact in
`data/profile/facts.json`. The `fact-check` reviewer in `review.yaml` is a
**hard gate** (not scored) — any unsupported claim fails the round. Agents
rewrite and reframe; they never invent.

Inferred skills (`Skill.inferred=true`) are evidence pointers: each carries
`evidence_fact_ids` resolving to literal facts. They may appear as
skills-section tokens (hard skills) and guide match-plan emphasis, but never
justify bullet or summary claims. Adjacent-tier matches (same ClusterMap theme,
not same canonical token) are never claimable as the JD's own term.

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

### Redo — forward-only, never destructive

`services/redo.py` re-runs any stage (`pull`/`extract`/`tailor`/`render`) over
explicitly chosen jobs at any status. It exists because the automatic paths are
deliberately one-way: `merge.decide()` freezes `jd_text` once a job leaves
`raw`, and `reprocess()` skips anything `has_progress()` covers. Those guards
stay; redo is the explicit escape hatch, never a mode.

Three invariants, all enforced by `tracking/stages.py::advance`:

- **Never regresses.** Status is a high-water mark. A rendered job stays
  rendered through a re-pull + re-extract + re-tailor.
- **Never rejects.** `rejected` ranks below `raw`, so the filter and relevance
  gates cannot fire under `never_regress`. Fresh fit scores are still written.
- **Never deletes.** New `ResumeVersion` rows are appended under an incremented
  `attempt`; `tailor_model` records which model produced them.

`StageScope(job_ids, any_status, never_regress)` is how the funnel stages in
`discovery/pipeline.py` run over explicit ids. `StageScope()` reproduces the
automatic funnel exactly — that default is the regression guard.

Re-pull deliberately bypasses `find_existing`/`decide`/`_apply` and refreshes
the row in place; a `dedup_key` that would collide with a sibling keeps the old
identity and takes only the text.

Per-job stage failures are durable: `services/errors.py::record_job_failure`
writes an `ErrorRecord` with `kind="job"` keyed `job:{id}:{stage}` (so repeats
coalesce into `count`), and `resolve_job_failures` closes it when that stage
later succeeds. `gather_isolated` no longer discards the exception — the cause
reaches the run result, the log, and the dashboard.

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

## Single-URL ATS readers (`url_ingest/ats_readers.py`)

Add-from-URL routes a pasted posting through `identify_host` (pure, no network)
to a deterministic reader — the browser is never used for a recognized ATS.

- **The ATS's own JSON API is tried first; the page's JSON-LD is the fallback.**
  A posting page shows more than its body: location, workplace type, employment
  type, department, and compensation live in a sidebar or top bar that the API
  exposes as dedicated fields. schema.org `JobPosting` markup carries only a
  subset and many boards emit none of it, so preferring JSON-LD because it is
  free silently dropped exactly the facts this module exists to capture. The
  API result wins whenever it resolves; JSON-LD fills blank fields and takes
  over entirely when the API cannot resolve the job. `_prefer(*candidates)`
  owns that rule — first candidate with a `jd_text` wins, the rest fill its gaps.
- **Sidebar facts ride in `jd_text` as `Label: value` lines** (the shape
  `ashby.parse_ashby` already used), so the relevance gate, criteria
  extraction, and tailoring read them as part of the description.
  `_json_ld_meta_lines` renders the schema.org equivalents — `baseSalary`,
  `employmentType`, `jobLocationType`, `occupationalCategory` — which the
  4-field description-only mapping used to discard.
- **A reader returns `None`, never an `ExtractedJob` with an empty `jd_text`.**
  That is the contract `service.job_from_url` keys its LLM fallback on; an
  empty-but-present result suppresses the fallback and fails the ingest even
  though the JD is sitting in the static HTML. `_api()` converts every lookup
  failure to `None`, and it catches `ValueError` as well as `httpx.HTTPError`
  because a maintenance page or bot interstitial served with status `200`
  raises out of `.json()`, not out of the transport.
- **Two host kinds are still browser-eligible:** an unrecognized one, and a
  `detect.SINGLETON_ATS` portal (Tesla, Google Careers), which is recognized by
  host but builds its listings in JavaScript — static HTML holds nothing for
  either a reader or the LLM. Both reuse the already-fetched page via
  `fetch.upgrade_if_shell` rather than issuing a second request for it.
- **Routing reads the post-redirect `final_url`**, so a tracking or shortened
  link that lands on LinkedIn still reaches `read_linkedin_posting`.
- Workday goes through `workday.fetch_job_detail` (not a bare `httpx.get`) so a
  pasted URL inherits the same 429/5xx retry a board pull gets, and stores
  `jobPostingInfo.companyName` rather than the tenant slug — a slug as the
  company breaks `dedup_key` against the same requisition pulled from the board.

---

## Companies connector dispatch (`companies.py`)

`CompaniesConnector.fetch` delegates to the `harvest` seam: for each URL in
`self.urls` it calls `detect_ats`, looks up the backend in `_BACKENDS`, and calls
`backend(target, search, effective_limit, skip_seen)`. Each `CompanyUrl.limit`
overrides the global per-unit fallback. Any URL that fails detection or whose backend
raises `httpx.HTTPError` / a parse error is recorded on the returned
`FetchResult.failures` (url → reason) — it never aborts the run. The relevance
gate and cap run per URL; the union is not capped, so one prolific board cannot
consume another URL's budget.

To add a new backend: write `fetch_<name>(target, search, limit, skip_seen=None) -> list[RawJob]`
in a new module, add detection logic to `detect.py`, register in `_BACKENDS`.
Connector construction itself is table-driven: `CONNECTOR_SPECS` in `registry.py` is the
single enumeration of connector kinds; adding an ATS appends one `ConnectorSpec`.
Source Manager CRUD (`services/sources.py`) rides that same table: `ConnectorSpec`'s
unit-addressing half (`section`/`unit_items`/`admits`/`new_unit`) plus `find_unit`/
`spec_for` mean enable/limit/remove/add walk the specs instead of hand-enumerating kinds.

---

## Workday N+1 pattern (`workday.py`)

Workday boards can have thousands of global listings — pulling all then gating
locally is infeasible.

1. **POST** `…/wday/cxs/{tenant}/{site}/jobs` with `{"searchText": ..., "limit": 20, "offset": N, "appliedFacets": ...}` — paginated list, title + location only. Location facets are tenant-resolved and cached when every configured location matches; misses stay unfaceted.
2. **`title_relevance_gate`** prunes the list _before_ any detail fetch.
3. **GET** `…/wday/cxs/{tenant}/{site}{externalPath}` for each survivor → `jobPostingInfo.jobDescription` (HTML → text via `html_to_text`).

Safety ceiling: `_MAX_OFFSET = 1000` (≤51 pages) even if the tenant ignores
`searchText`. Keep `search.yaml` role anchors tight — the title-gate's
aggressiveness determines how many detail fetches are issued.

**Throttle-resilient.** A big board fires many list + detail requests, so both
HTTP calls go through `_request_with_retry`: transient statuses (`429`, `500`,
`502`, `503`, `504`) are retried with backoff — a numeric `Retry-After` is
honored, else exponential (`_RETRY_BACKOFF_S · 2ⁿ`, capped at
`_MAX_RETRY_SLEEP_S`) — for `_RETRY_ATTEMPTS` tries before the last error is
re-raised, so a persistently-throttled board still surfaces as a per-URL failure
(the companies connector isolates it) rather than aborting sibling URLs.

---

## Relevance gates (`text.py`)

| Function               | When used                                                                                                                               |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `title_relevance_gate` | Before JD text is available (Workday list rows, Tesla listing state)                                                                    |
| `relevance_gate`       | Full gate on title + JD; falls back to keyword search when no `role_anchors` are configured                                             |
| `primary_search_term`  | Picks the strongest term to send as `searchText` to Workday / Google; falls back to `role_anchors` if `titles` and `keywords` are empty |
| `primary_location`     | Picks the first configured location for ATS endpoints such as Lever that accept a free-form location filter                             |

---

## Hot paths (most-edited files)

| Path                                                 | Role                                                                                                                      |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- | ----------------- |
| `src/resume_agent/llm_runner.py`                     | `build_model` provider seam + `AgentRunner` adapter                                                                       |
| `src/resume_agent/profile/corpus.py`                 | Source registry: manifest + add/remove + legacy migration                                                                 |
| `src/resume_agent/profile/matrix.py`                 | Derived skill matrix + overrides (ban/alias/forbid/category)                                                              |
| `src/resume_agent/taxonomy/groups.py`                | Skill-group vocabulary + durable token-to-group taxonomy + delta classifier                                               |
| `src/resume_agent/profile/synthesis.py`              | Verified synthesis: deck → excerpt-backed facts (synthesize → verify → one repair round)                                  |
| `src/resume_agent/profile/fragments.py`              | Fragment cache walk: one cache/staleness policy, per-mode producers (literal, synthesis, project), concurrent production  |
| `src/resume_agent/profile/github_harvest.py`         | Deterministic GitHub project-source selection, materialization, supersession, and cleanup                                 |
| `src/resume_agent/profile/project_extractor.py`      | Project-only structured extraction that cannot emit employment or education facts                                         |
| `src/resume_agent/profile/coach.py`                  | Coach turn validation, topic-aware context, and structured-output agents                                                  |
| `src/resume_agent/interview/agent.py`                | Mock interviewer persona, turn/debrief validation, transcript elision                                                     |
| `src/resume_agent/services/profile_coach.py`         | Coach session turns, draft approval, recap, rebuild, and impact orchestration                                             |
| `src/resume_agent/sessions/store.py`                 | Session substrate: file custody every turn-per-run session kind rides (ADR 0006)                                          |
| `src/resume_agent/discovery/connectors/detect.py`    | ATS detection (singleton → L1 → L2)                                                                                       |
| `src/resume_agent/discovery/connectors/companies.py` | Dispatch table + per-URL fail isolation                                                                                   |
| `src/resume_agent/discovery/scraper/dashboard.py`    | Opt-in learned-recipe browser replay; cache in `data/scraper_recipes/`                                                    |
| `src/resume_agent/discovery/connectors/workday.py`   | Workday CXS list → gate → detail                                                                                          |
| `src/resume_agent/discovery/connectors/tesla.py`     | Tesla visible-browser portal: state capture + same-origin detail fetches                                                  |
| `src/resume_agent/discovery/connectors/google.py`    | Google Careers results-page `AF_initDataCallback` parser (list-only)                                                      |
| `src/resume_agent/discovery/connectors/text.py`      | Relevance gates + `html_to_text`                                                                                          |
| `src/resume_agent/discovery/connectors/runner.py`    | Pull orchestration: concurrent fetch (bounded by `pull_concurrency`), serial canonical-order ingest, `+N added` telemetry |
| `src/resume_agent/concurrency.py`                    | `gather_isolated` — ordered, error-isolated async fan-out                                                                 |
| `src/resume_agent/discovery/ingest.py`               | `save_or_upgrade`, source-priority logic                                                                                  |
| `src/resume_agent/tracking/dedup.py`                 | `compute_dedup_key` — `company                                                                                            | normalized_title` |
| `tests/test_discovery_ingest.py`                     | Ingest + dedup + priority tests                                                                                           |
| `src/resume_agent/settings_sections.py`              | Single enumeration of customizable settings: bundle scope + reset targets                                                 |

---

## Known design notes

- **Boards page in SQL.** `tracking.board_query` selects only the returned page,
  and row projection happens afterward. `PipelineItem` ships a bounded
  `jdPreview`; the full `jd_text` is available only from `JobDetail`. Two costs
  the page read must not re-incur: `jd_text` stays `defer()`-ed on shortlist and
  triage (only `PipelineRow` reads it — pinned by
  `test_shortlist_and_triage_rows_never_touch_jd_text`), and the `companySize`/
  `skills` token-to-raw-value scans are derived once per request via
  `derive_filter_values` and passed to both `board_page` and
  `board_facet_counts`.
- **Profile coaching is turn-per-run and evidence-locked.** Durable sessions follow
  ADR 0006, while the ADR 0005 amendment requires every draft note to retain
  verbatim quotes from the current user turn. The former batch interview API,
  CLI command, and web panel are retired; its history remains read-only input
  for avoiding repeated questions.
- **Tailoring is fast by default.** `config/review.yaml.example` materializes as
  the two-round roster with mid-tier writers and one `MergedPanelReview`
  advisory call; the premium fact-check gate remains separate. Deep mode uses
  `config/review_deep.yaml` through CLI `tailor --deep` or API `deep: true`.
  Advisory critiques are split back into their configured named rows, and each
  `TailorRound` records draft/panel/revise wall-clock seconds.
- **A round's score is a measurement or it is `None` — never `0`.**
  `PanelVerdict.aggregate_score` is the weighted mean over non-gate reviewers;
  with no weighted critique the mean is _unknown_, so it is `None` and `passed`
  falls back to `gate_passed`. It used to be `0`, and the panel used to be
  skipped whenever the provenance gate failed, so 25% of stored rounds reported
  `0` for a resume that was never measured. **The panel now always runs** — a
  broken citation says nothing about quality, and skipping it left the reviser
  with no advisory feedback for that round. `services/revision.py` and
  `evals/metrics.py` already modelled the score as optional; the runtime is the
  one that disagreed. `scripts/tailor_health.py` reports the distribution.
- **The writer only ever sees facts it may render.** `renderable_profile()`
  (`tailor/provenance.py`) strips inferred soft/domain skills from the profile
  handed to the tailor and reviser, because `check_provenance` rejects them
  wherever they are cited. The gate still indexes the **full** facts, so a
  forbidden id arriving via a match plan or a hand-edited resume still fails —
  this narrows the menu, it does not relax the rule. Match-plan input is
  deliberately unfiltered (inferred skills legitimately guide emphasis).
- **The summary carries its own provenance.** `ResumeContent.summary_provenance`
  lists the fact ids the summary draws on, and rides the same `_referenced_uses`
  path as every other citation (as an `entity` use, so an inferred pointer there
  is rejected). Without it the gate could not check the summary at all and
  `resolve_evidence` showed the reviewer only facts cited _elsewhere_, so a true
  summary claim read as unsupported. Empty is valid — versions stored before the
  field still validate.
- **The reviser gets the job description; `jd_text` is required, not defaulted.**
  It is handed `ats-keyword` and `hiring-manager` critiques, which are entirely
  about fit, so without the JD it was being asked to fix complaints it could not
  read. `compose_revise_input` orders stable context (profile, JD) before
  volatile context (current resume, this round's critiques) to keep the
  cacheable prefix intact across rounds. A revision builds on `_best_base` — the
  best round so far by (gate-clean, score) — not the last, so a regressed round
  cannot become the base for the next one.
- **A citation slip is not a quality round.** A round that fails _only_ on
  provenance ids does not consume one of `max_rounds`, up to
  `ReviewConfig.provenance_retry_budget` (default 1; `0` reproduces the old
  counting). `_is_citation_slip` requires provenance to be the sole failing gate
  _and_ a real panel score, so a resume the panel also rejects still pays for its
  round.
- **Gate failures are named, not conflated.** `ResumeVersion.fact_check_passed`
  is the AND of every gate, so it cannot say which one blocked — it labelled a
  provenance-only failure as "Fact-check failed" on rounds where fact-check never
  ran. `verdict.failing_gate_names` owns the rule and `ResumeVersionOut.failedGates`
  carries it to the UI.
- **`score_threshold` and `match_plan_enabled` are unmeasured.** Both shipped
  rosters now set `score_bands: true` on every advisory reviewer (five private
  scales were being averaged against one fixed threshold) and
  `early_stop_on_regression: true`. The threshold stays at 85 and the match plan
  stays off until the eval arms in `evals/RESULTS.md` are actually run — see the
  2026-07-27 baseline entry there.
- **Agent prompts are registry-projected; guidance is layered.**
  `prompts/registry.py` imports the complete invariant instruction composition
  from each production agent builder. Per-agent guidance lives in
  `config/agent_guidance.yaml`, is capped at 4,000 characters, and is appended
  beneath immutable rules by `prompts/guidance.py:with_guidance`; it may steer
  tone, emphasis, or process, never facts. `reviewer-fact-check` is the only
  non-editable integrity gate. API: `GET /api/agents/prompts` and
  `PUT /api/agents/prompts/{key}`.
- **Rendering is template-id based.** The web contract is `{template,
fitOnePage}`; legacy `template_path` and `output_dir` remain runtime-only CLI
  fields. Bundled templates are anchored in `render/templates.py`; validated
  custom `.typ` uploads live under the tenant `config/templates/` directory.
  Custom stems are path-safe, Typst compilation is root-pinned, and uploads
  replace live templates only after a successful validation compile. Deleting
  an active custom template falls back to `classic`; missing templates never
  silently fall back during rendering.
- **Railway is a single-volume, single-owner deployment.** Session cookies and
  bearer tokens share the API guard; `/app/data` owns DB/config/output/secrets;
  browser-only sources return explicit degradation failures in cloud. Admin
  import validates and stages the archive, then uses rollback-safe child swaps
  because the mounted volume root itself cannot be renamed.
- **Skill groups are a derived display axis.** `MatrixRow.group` comes from the
  active data root's `taxonomy/skill_groups.json` (token → slug, fixed 20-slug
  vocabulary in `taxonomy/vocabulary.py`). Profile builds classify only missing
  tokens with the cheap tier; failed batches remain absent and retry on the next
  build. Match-gap refreshes apply the saved map without an LLM, and
  `overrides.yaml`'s `group:` map wins over taxonomy. User re-categorizations
  from Settings > Skill groups live in `data/profile/group_corrections.json`,
  win over both overrides and taxonomy, and are replayed by
  `decorate_matrix_groups` on every matrix rebuild. The LLM classifier never
  reads or writes corrections, and `MatrixRow.group_source` records whether a
  correction, override, or taxonomy assigned the row. Groups never alter
  `facts.json` or the hard/soft/domain categories used by fact-lock; unassigned
  rows render as Other.
- **Skill taxonomy is three-level and correction-locked.** The fixed 20-slug category
  vocabulary lives in `taxonomy/vocabulary.py` (shared by the profile matrix group axis
  and the constellation); LLM-clustered domains parent to exactly one category with a
  deterministic per-category cap (`Settings.domains_per_category_cap`, default 12)
  enforced in `classification._project_domains`, never trusted to the model. User edits
  (move/rename/merge/add/remove/alias) write intent entries to
  `data/taxonomy/taxonomy_corrections.json` via `services/taxonomy.py` and are replayed
  last by `apply_taxonomy_corrections` on every load — corrections beat LLM output;
  dangling references are inert. Legacy cluster files load aliases-only (themes ignored),
  so the first refresh reclassifies once; legacy `theme`-kind suggestions are purged.
- **GitHub depth is two-tier; dossiers win.** `profile/github_harvest.py` writes
  qualifying repositories' root docs (README files plus CLAUDE, CONTEXT, and
  AGENTS markdown, capped at 30 KB per file) as deterministic
  `sources/github--<repo>.md` documents with `origin="github"` and
  `mode="project"` during build phase 0 and `profile sync-github`. A markdown
  upload with `repo_url:` frontmatter, such as output from
  `.claude/skills/project-dossier`, supersedes the auto-document for the same
  normalized repository URL. Harvest also discovers root files named
  `*dossier*.md` (max 5 per repo, 30 KB each) whose `repo_url` frontmatter
  matches the repo; each becomes its own `github--<repo>--<stem>.md` project
  source and replaces that repo's README virtual doc. Manual uploads still
  supersede all harvested docs for the repo. `project_extractor.py` can emit exactly one Project
  plus skills, never Experience or Education. GitHub failures become build
  warnings; rate-limited harvests stop early without deleting existing sources.
- **Profile rebuilds regenerate inferred skills.** `profile build` strips and re-derives
  all `inferred=true` skills; durable corrections belong in `data/profile/overrides.yaml`,
  not hand-edits to facts.json.
- **Synthesis ingest is text-only.** markitdown converts slide text frames, tables, and
  speaker notes; images/diagrams are skipped, and an LLM image description is never
  verification evidence (it would punch a hole in fact-lock). Put key numbers in slide
  text or speaker notes so they are extractable.
- **`dedup_key` is not unique — location guard.** `compute_dedup_key` stays
  `normalize(company)|normalize_title(title)`; `find_existing` additionally requires
  `locations_compatible` (blank = wildcard, else city-token subset) on its identical-JD,
  dedup_key, and keyless-fingerprint branches (URL match exempt). Multi-location
  same-title requisitions are sibling rows sharing a dedup_key. See
  `docs/adr/0001-dedup-key-plus-location-guard.md`.
- **Workday sends location facets when safely resolvable.** The first plain page's
  location facet descriptors are matched case-insensitively against every configured
  `search.yaml` location, then cached under `data/workday_facets/{tenant}-{site}.json`.
  Partial/malformed matches, cache failures, and empty faceted restarts fall back to
  searchText-only paging. Category/job-family facets remain out of scope.
- **Tesla/Google portals are reverse-engineered.** Google's `ds:1`
  `AF_initDataCallback` carries complete list rows and full JDs; a missing or malformed
  jobs callback raises a per-URL parse failure. Tesla's site is Akamai-gated: the
  visible `TeslaPortal` only passes with **real Chrome** (`channel="chrome"`),
  `--disable-blink-features=AutomationControlled` (so `navigator.webdriver` is
  `false`), and a **fresh non-persistent context** (a persistent profile keeps a
  poisoned `_abck` cookie from a prior denial). All three are required; bundled
  Chromium or `webdriver=true` is served "Access Denied" and the `state` XHR never
  fires. `_capture_state` retries past a throttled cold denial and raises
  `TeslaStateUnavailable` (isolated by `_failure_reason`, never aborting the pull).
  Live schema: listing location is a code resolved via `state.lookup.locations`; the
  detail endpoint is `cua-api/careers/job/{id}` (no `apps/`) and JD prose lives in
  `jobDescription`/`jobResponsibilities`/`jobRequirements`/`jobCompensationAndBenefits`
  (`description` is empty). A companies connector containing Tesla opts out of
  concurrent fetch and is serialized with other visible-browser connectors by the
  pull runner. Either portal can change without notice, but its failure never aborts
  other company URLs.
- **Limits are per source unit.** Every board, careers URL, aggregator, and scrape
  target can set an optional positive `limit` in `connectors.yaml` or Source Manager.
  The global `--limit` is the per-unit fallback; `harvest` gates, skips known rows, and
  caps each unit independently, never the union.
- **Adzuna enrichment needs a real (non-headless) browser.** The API returns only a truncated snippet,
  and `redirect_url` is a bot-gated `/land/ad/` click-tracker — bare `httpx` gets `403` and _headless_
  Chromium is challenged ("suspicious behaviour"); only a non-headless browser follows the redirect to
  the employer/aggregator posting (Dice, Greenhouse, …). So `AdzunaConnector.fetch` (when
  `enrich_details=True`, the default) relevance-gates the snippets, then `enrich_adzuna_jobs` calls
  `browser.render_pages` to drive **one shared visible browser context** over every survivor's
  `redirect_url` (distinct ads are safe; re-clicking the _same_ ad boomerangs to a search page),
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
  per-agent config via `retry_kwargs()`; retries live in `AgentRunner` behind the `is_transient`
  predicate (rate-limit/timeout/5xx retry with exponential backoff; auth/schema/parse failures
  surface after one call); agno's own retry is disabled via `retry_kwargs() == {"retries": 0}`.
  A job whose LLM work fails is skipped (left in its prior status) and retried next run.
- **Profile build fans out per document.** `extract_fragments` /
  `extract_synthesis_fragments` share one cache walk; production runs concurrently via
  `gather_isolated` with the permit acquired only in `llm_runner.acall`. The CLI and API both
  build through `services/profile_build.run_corpus_build` -- the single place the facts+matrix
  bound-artifact pair is written.
- **File SQLite runs WAL.** `make_engine` sets `journal_mode=WAL`, `busy_timeout=30000`,
  and `synchronous=NORMAL` on every file-backed connection so the API's writer threads wait
  instead of failing immediately with `database is locked`.
- **Industry normalization is scoped.** `_normalize_job_industries` walks only the
  just-extracted batch plus rows with a pending `_industry_candidate` or legacy SIC keys --
  never the whole table.
- **Board bulk actions are transactional.** `bulk_apply` uses one batched load plus the
  `progressed_job_ids` gate, then one commit. `delete_job_row` is the unguarded cascade shared
  with guarded `delete_job` and prune.
- **Mock interviews are practice artifacts, not progress.** `interview/store.py`
  keeps one durable session JSON per interview under `data/interview/`
  (turn-per-run, ADR 0006), with the JD + tailored-resume snapshot frozen at
  opening. The interviewer stays in character (no mid-session coaching); the
  debrief run scores only questions actually asked. No corpus writes — fact-lock
  untouched — and sessions never gate job deletion (`has_progress` unchanged);
  the job delete endpoint removes the job's session files. Voice input rides
  `llm_runner.transcribe` (`Settings.transcribe_model`, Gemini/OpenAI only,
  default `gemini:gemini-2.5-flash`) through `POST /api/transcribe`; audio is
  never persisted.
  Both the coach and interview stores are adapters of the Session substrate
  (`sessions/store.py`); custody bugs are fixed there, once. `TurnRejected` and
  `format_with_retry` live in `sessions/turns.py`, shared by both stacks.
- **Email identity is authoritative in multi-user auth.** Verified email is the
  login identifier; the legacy username fallback is accepted only while a user
  has no email. Registration, reset, and email-adoption codes are single-use,
  purpose-isolated rows with bounded attempts. Password changes, resets, and
  explicit revoke-all increment `session_epoch`; the current response receives
  a freshly signed cookie while older cookies stop verifying. Rate budgets are
  durable SQLite rows and every check-plus-record operation uses one
  `BEGIN IMMEDIATE` writer transaction.
- **Google identity is pinned to `sub`, not email.** An exact boolean
  `email_verified` claim is required before the first email-based link; a
  different existing `google_sub` is never overwritten. Sign-in scopes remain
  identity-only. Gmail consent is a separate incremental flow and keeps its
  readonly + compose scopes; `gmail.send` remains out of scope.
- **Gmail is multi-user; drafts only, never send.** The platform OAuth client
  (`GOOGLE_OAUTH_CLIENT_ID/SECRET`) can be overridden per user via
  `secrets.env`; per-user tokens live at `{workspace}/gmail_token.json`
  (`gmail/auth.py` is the only credential seam; scopes = readonly + compose).
  The web callback authenticates via a signed link-token state, never the
  session cookie. An in-process scheduler (`gmail/scheduler.py`, every
  `gmail_sync_interval_hours`) runs `services/gmail_sync.run_gmail_sync`
  per connected user — sync proposals and deterministic stale-application
  reminders (`services/reminders.py`, episode-keyed dedupe in
  `Notification.message_id`) land in the notification bell; nothing
  auto-applies. `services/email_writer.py` grounds drafts in facts.json
  only (human gate, no LLM fact-check round) and saves them as in-thread
  Gmail drafts via `EmailDraft` rows; drafts never gate job deletion but
  cascade on delete. `gmail.send` is permanently out of scope.
- **The customizable settings surface is declared once.** `settings_sections.py`
  holds `SETTINGS_SECTIONS`: twelve rows naming each transferable, resettable
  unit and the canonical relative paths it owns (`config/connectors.yaml`,
  `data/profile/overrides.yaml`). It is an **allowlist** — it spans the
  workspace root alongside `secrets.env`, `gmail_token.json`,
  `resume_agent.db`, and `config/gmail_credentials.json`, so a file not named
  there can neither leave a workspace in a settings bundle nor enter one from
  an imported bundle. `services/settings_bundle.py` exports and imports that
  set as a tar.gz (`GET/POST /api/settings/bundle`), replacing the sections a
  bundle names and leaving the rest untouched — a bundle can add or replace
  settings but never clear them. Reset (`POST
/api/settings/sections/{id}/reset`) copies the shipped `.example` when one
  exists and deletes the file otherwise, which is the same rule
  `provision_workspace` uses to seed a fresh workspace. Import validation uses
  the artifacts' **models** but not their read-time loaders:
  `load_group_corrections` and `load_taxonomy_corrections` return an empty
  ledger on corruption, which is right for reading and catastrophic for
  importing.
