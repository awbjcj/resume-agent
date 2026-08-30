# API layer developer reference

Migrated from the project root `CLAUDE.md` (2026-08-15, CLAUDE.md split) — loads only when working under `src/resume_agent/api/`.

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
- **Terminal runs are also durable.** `RunManager.on_terminal` records exactly one
  `RunCompletion` row when a run reaches `succeeded`, `failed`, or `cancelled`;
  callback failures are logged and must never replace the worker's real outcome.
  `GET /api/run-completions` returns newest-first history (50 by default), while
  the read endpoints mutate only `read_at`. These records are independent from
  Gmail-derived application notifications.
- **Saved board views store the existing URL contract.** `/api/board-views`
  provides workspace-scoped CRUD for triage, shortlist, and pipeline. Its
  `queryString` is the canonical `stateToParams` representation, including any
  endpoint-local flags such as triage's `archived`; do not add a second filter
  schema to the API.
- **Errors** use one envelope `{ "error": { code, message, details? } }` via
  `ApiException` + handlers in `api/errors.py`.
- **Runtime/auth boundary:** `create_app(..., app_mode="local")` auto-activates
  one default workspace and bypasses account auth; the CLI confines that mode
  to loopback. `app_mode="hosted"` enables session/PAT authentication and
  per-request tenant context. `Settings.cors_origins` remains the CORS allowlist.
- **In-memory sqlite tests** need a shared connection: `make_engine` gives
  `sqlite://` a `StaticPool` + `check_same_thread=False` so the request threadpool
  sees the schema the lifespan thread created.
- **Board filters are declared once.** `tracking/board_query.py` owns the shared
  shortlist/pipeline/triage selection, sorting, paging, and facet expressions;
  `board_filter_query(default_sort)` only maps the shared HTTP query surface
  into that contract. Triage's extra `archived` flag stays endpoint-local via
  `dataclasses.replace`.

---

## Auth, runs, and job-scoped surfaces

- **A per-job surface must recognise a bulk run covering that job.** Per-job
  launchers tag runs with `meta.jobId`; the Pipeline bulk actions tag them with
  `meta.jobIds`. `artifact-runs.ts::runCoversJob` is the one predicate that
  reads both — checking only `jobId` made a bulk cover-letter run invisible to
  the job's own Cover letters tab, which offered a second Generate for a job
  already being generated for, and `POST /api/cover-letters` has no singleton
  key, so it really ran twice. An approved-scope bulk run resolves its targets
  server-side and carries neither key; it is invisible here by necessity.
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
