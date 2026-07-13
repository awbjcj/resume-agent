# Multi-User Tenancy — Design

**Date:** 2026-07-12
**Status:** Approved with pre-implementation correctness amendments
**Scope:** Expand resume-agent from a single-account tool to a small-group
multi-user system: invitation-code registration, admin/user roles, per-user
LLM budgets and resource quotas, user-specific tokens/links, per-user
databases and workspaces, and admin management surfaces (HTTP CLI + web UI),
modeled on vsda-deep-agent's user management and deep-agents-ui's admin panel.

---

## 1. Requirements (decided with the user)

| Decision     | Choice                                                                                                                                                            |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Limits       | Per-user LLM token budgets **and** per-user job/run quotas (no seat cap)                                                                                          |
| LLM keys     | Hybrid — shared server keys (budget-enforced) by default; a user-supplied provider key exempts that user's calls from the budget                                  |
| Registration | Single-use, admin-minted invitation codes; no email verification step                                                                                             |
| Roles        | Two: `admin` and `user`                                                                                                                                           |
| Tokens       | User-scoped session cookie + revocable personal access tokens (PATs) + short-lived signed link tokens for SSE/downloads; the static shared `api_token` is removed |
| Isolation    | Full per-user workspace: SQLite DB, profile corpus, config YAMLs, output, runs, non-LLM secrets                                                                   |
| Admin CLI    | Thin HTTP client over an admin API (the same API powers the admin web UI)                                                                                         |
| Migration    | Multi-user always (no mode flag); existing env credentials seed the first admin; the existing `data/` contents become that admin's workspace                      |

**Chosen architecture (Approach A):** request-scoped `UserContext` + per-user
engine registry + one shared `system.db` for auth/budgets. Rejected: row-level
tenancy (`user_id` columns — contradicts the per-user-database requirement and
poisons every query with a tenant filter) and app-instance-per-user (N
RunManagers in memory, fragmented cross-cutting concerns). Context reaches the
domain layer via a contextvar — see ADR-0003 and §2.

Grilling session 2026-07-12 resolved: contextvar propagation (ADR-0003),
Data root / Workspace glossary split (CONTEXT.md), seed-only bootstrap,
role-less invites, role-equivalent PATs, web-UI-only remote members,
self-service export + admin-only delete, shipped limit defaults, failed-attempt
rate limiting, admin budget exemption.

### Pre-implementation correctness amendments (2026-07-12)

The implementation-plan audit against the current runtime found several
places where the original snippets would violate this design. These
amendments are normative and take precedence over optimistic snippets in the
three plans:

1. **Multi-user really is always on for file-backed apps.** Every file-backed
   server boot initializes `system.db`; an empty user table without both seed
   credentials is a startup error. Only the explicit in-memory SQLite test
   adapter retains the legacy single-user path. There is no credential-based
   fallback that can silently start a production server in legacy mode.
2. **The request seam covers every tenant resource, not only SQL sessions.**
   `UserContext` carries the Workspace paths, workspace engine, shared system
   engine, effective settings, and own-key provider provenance. Request
   resource adapters resolve config stores, document stores, secrets files,
   profile/output/taxonomy paths, and direct engine/settings access from the
   active context. No guarded router may read a mutable tenant resource from
   process-global `app.state`.
3. **Workspace provisioning is template-complete and self-healing.** It copies
   every supported `config/*.example` artifact without overwriting user edits,
   and `build_context` idempotently provisions missing directories so a crash
   after registration cannot leave a permanently unusable account.
4. **Legacy adoption is a recoverable transaction.** A journal records each
   child move; failures roll moved children back when possible and otherwise
   leave a deterministic resumable journal. Bootstrap distinguishes an empty
   user table from a corrupted non-empty/no-admin table and never seeds a new
   admin merely because the admin query returned no row.
5. **Authentication inputs are constrained at the API boundary.** Usernames
   use a stable normalized, path/header-safe syntax; passwords and token names
   have explicit length bounds; limit values are non-negative. Password hashes
   remain backward-compatible with existing PBKDF2 strings but new/verified
   weak hashes are upgraded to the current iteration policy. Session signing
   mixes the complete password hash, and the cookie's `Secure` flag follows
   the effective HTTPS scheme so localhost HTTP CLI login remains usable.
6. **Link tokens are capabilities, not general authentication.** Normal guarded
   routes accept only a session cookie or header PAT. A link token is accepted
   only by an explicitly link-enabled SSE/download dependency and only when
   its signed purpose and authenticated user own the requested resource. An
   `sse` token can never authorize `/api/jobs`, mutations, or a download.
7. **Usage accounting covers sync and async calls.** Recording lives in the
   successful return path of `AgentRunner.run` and `AgentRunner.arun`, which
   are the actual common seam; `acall` alone misses synchronous calls. The
   system engine and own-key provenance come from `UserContext`, never a
   process-global recorder or cwd-derived `env_settings()` comparison, so
   multiple app instances cannot cross-write usage.
8. **All run operations are tenant-scoped.** Run JSON lives in the submitting
   user's Workspace `runs/`; singleton keys include the user id; list/get/SSE/
   cancel and recovery enforce ownership; persisted failures carry a typed
   `errorCode` as well as human text. Foreign run ids return 404.
9. **Quota checks preserve their stated semantics.** Job-cap tests cover both
   inserts and upgrades at the cap, archived rows do not count, and per-user
   pull singletons prevent concurrent same-user batches from racing the cap.
10. **User deletion and root import are failure-atomic.** Deletion first checks
    all guards, evicts handles, quarantines the Workspace by rename, commits
    credential cleanup/user deletion, then removes the quarantine; failures
    restore it rather than using `ignore_errors=True`. Whole-root import closes
    every engine once, validates/rebuilds before declaring success, and keeps
    the existing rollback archive if restoration fails.
11. **Admin/account UI follows the existing generated client and design
    system.** React 19 + React Router 7 + the installed base-nova shadcn
    components are used with loading/error/empty states, accessible dialogs,
    responsive layouts, and role-gated routes. Raw fetch helpers, bare form
    markup, and `window.confirm` reference snippets are not implementation
    contracts.
12. **The local domain CLI rebases paths as well as settings.** Default
    `data/...` and `config/...` arguments map into the selected Workspace;
    explicit user-supplied paths remain untouched. Activating a context alone
    is insufficient because the current CLI passes many literal paths.

---

## 2. Data layout & tenancy core

```
data/
  system.db                 # NEW: users, invite_codes, api_tokens, usage_events, system_settings
  users/
    <user_id>/              # one full workspace per user (today's data/ shape, relocated)
      resume_agent.db       # jobs/applications/resumes/cover letters — schema UNCHANGED
      profile/              # facts.json, corpus, documents/, overrides.yaml
      config/               # search.yaml, connectors.yaml, review.yaml, prune.yaml
      secrets.env           # per-user non-LLM keys (GitHub, Adzuna) + optional own LLM keys
      output/  runs/  scraper_recipes/  workday_facets/  taxonomy/
```

- **`UserContext`** is the single new seam: the authenticated `User` row, the
  typed workspace paths, a per-user SQLModel engine, the shared system engine,
  own-key provider provenance, and an **effective `Settings`**
  (server settings overlaid with the user's `secrets.env`, config dir, and
  data paths). The auth dependency resolves it per request; routers and
  services stop reading `app.state.engine` / global `data/` / `config/` and
  draw everything from the context.
- **Engine registry:** `user_id → engine` map on `app.state`; engines created
  lazily via the existing `make_engine` (WAL, busy timeout carry over). No
  eviction for a small group; all engines closed on shutdown.
- **Run workers** already open their own DB sessions; run submission captures
  the submitting user's context (engine + paths) so workers never touch the
  request session. Run records live under the owner's Workspace, gain a
  `user_id`, and every list/get/SSE/cancel operation enforces ownership.
- **The job DB schema does not change.** Isolation is by file, not by column,
  so `tracking/queries.py` and every invariant (fact-lock, source priority,
  dedup, archive/prune) are untouched.
- The CLI constructs a local `UserContext` directly (no HTTP) — one seam, two
  adapters, same as the existing services architecture.
- **`user_id` is an opaque short hex id** (e.g. `uuid4().hex[:12]`), used as
  the Workspace directory name. Usernames are display/login identity and can
  be renamed without touching paths.

**Context propagation (ADR-0003):** a `contextvars.ContextVar` holds the
active `UserContext`. Exactly three set-points: the API auth dependency (per
request), the RunManager worker wrapper (per background run), and the CLI
entrypoint (per invocation). `get_settings()` returns the active context's
effective Settings when one is set and falls back to env-derived settings
otherwise (tests, legacy local mode) — so the 36 domain-layer call sites do
not change. `AgentRunner.run` / `AgentRunner.arun` read the active context to
record usage.
Crossing an `asyncio.run` or threadpool boundary must capture and restore the
context explicitly; that capture is part of the seam's contract, and tests
assert isolation under concurrent mixed-user requests.

## 3. Auth, registration, and tokens

New tables in `system.db` (SQLModel, same `init_db` pattern):

- **`User`**: id, unique username, pbkdf2 password hash (reusing the
  `api/auth.py` helpers), role (`admin` | `user`), `disabled_at`, per-user
  limit overrides (`weekly_token_budget`, `max_active_jobs`,
  `max_concurrent_runs` — NULL = system default), timestamps.
- **`InviteCode`**: hashed single-use code, `created_by`, `expires_at`,
  `used_by` / `used_at`, `revoked_at`. Codes are `inv_`-prefixed random
  secrets shown once at mint, stored hashed (symmetric with PATs). Codes are
  **role-less** — every registration mints `role=user`; promotion is a
  separate explicit `set-role`. Default expiry 14 days, overridable at mint.
- **`ApiToken`**: user_id, name, sha256-hashed token, `created_at`,
  `last_used_at`, `revoked_at`.
- **`UsageEvent`**: append-only per-LLM-call usage log (user_id, ts, provider,
  model, token counts, weighted total, `own_key` flag).

Flows:

- **Register:** `POST /api/auth/register {username, password, inviteCode}` —
  validates and consumes the code atomically (one code, one account, even
  under concurrent registration), creates the user, provisions the workspace
  from the `.example` config templates.
- **Login/session:** stateless HMAC cookie retained, payload becomes
  `user_id:expiry`; the signature mixes in a fragment of the user's password
  hash so a password change (or admin reset) invalidates that user's sessions
  with no server-side session table. Cookie attributes: `HttpOnly`,
  `SameSite=Lax`, `Secure` when served over HTTPS.
- **Personal access tokens:** `rat_`-prefixed random secrets shown once,
  stored hashed; sent as `Authorization: Bearer` — **header-only, never
  accepted via query param** (link tokens are query-only; the two surfaces do
  not overlap). PATs are **role-equivalent**: a PAT is the user, so an
  admin's PAT can call `/api/admin/*`. No scoped tokens for a trusted small
  group. Request auth resolves session cookie → PAT → 401.
- **Rate limiting:** in-process fixed-window throttle on _failed_ attempts at
  the two unauthenticated endpoints (`login`, `register`): 10 failures per
  (username, client IP) per 15 minutes → 429 `RATE_LIMITED` until the window
  rolls; success resets the counter. In-memory only (single process); resets
  on restart, which matches the threat model. No lockout flag on the user row
  — an attacker must not be able to lock the real user out durably.
- **Link tokens:** SSE (`EventSource`) and selected `<a>` downloads cannot set headers,
  so `POST /api/auth/link-token` mints a short-lived (~10 min) signed
  `user_id:purpose:expiry` capability accepted only via `?token=` on the
  matching purpose-bound route. It is never part of general request auth.
  This replaces the static shared `api_token`, which is removed.
- **Bootstrap:** whenever the `users` table is empty (fresh deploy or legacy
  adoption), `AUTH_USERNAME` / `AUTH_PASSWORD_HASH` are **required** and seed
  the admin row; the server refuses to start without them. Registration is
  invite-only, so an instance with no admin would otherwise be permanently
  locked out. The env pair is **seed-only**: it is read exactly once, when
  the table is empty; thereafter `system.db` is the sole credential
  authority and the env values are ignored. **Behavior change:** rotating
  `AUTH_PASSWORD_HASH` no longer rotates the admin password once users exist
  — the admin changes it on the Account page like everyone else.

## 4. Budgets, quotas, and enforcement points

**Token budgets (shared-key users only):**

- **Recording** at the one seam every production LLM call passes through:
  `AgentRunner.run` / `AgentRunner.arun` append a `UsageEvent` to `system.db` (own short
  session; WAL absorbs concurrent writers). Weighted totals mirror
  vsda-deep-agent (input + output weighted; cache reads discounted).
- **Enforcement is per phase, not per call:** when a run phase starts (pull
  scoring, discovery, tailor, cover letters, profile build), the service sums
  the user's rolling 7-day usage once; over budget → the run fails fast with
  typed `BUDGET_EXCEEDED`. Mid-run overshoot is tolerated by design — no
  `system.db` read inside the semaphore-guarded leaf.
- **Own-key exemption:** `resolve_api_key` knows the provider; when the
  effective key came from the user's `secrets.env` rather than server env,
  usage is still recorded (`own_key=true`, for visibility) but never counted
  against the budget.
- **Admin exemption:** admins are exempt from budget _enforcement_ but fully
  _recorded_ (their usage appears in the aggregate view). Same mechanics as
  the own-key exemption — record always, enforce conditionally — one code
  path, two exemption reasons. Resource quotas still apply to admins.
- **Recording never breaks the call:** a failed `UsageEvent` write logs a
  warning and the LLM result still returns; accounting is best-effort,
  enforcement reads whatever was recorded.

**Resource quotas (all users, own key or not):**

- `max_active_jobs`: checked in the `save_or_upgrade` ingest path — at the
  cap, pulls stop **adding** rows and report `quota reached` in the run
  summary; upgrades to existing rows still apply.
- `max_concurrent_runs`: `RunManager.submit` counts the user's in-flight runs
  and rejects beyond the cap (default 2) with `QUOTA_EXCEEDED` (HTTP 429).
  This is also the fairness lever for the process-global `llm_concurrency`
  semaphore, which stays shared.
- Defaults live in `system_settings` (admin-editable); per-user override
  columns on `User` win when set. `NULL` override = use the system default;
  `0` = unlimited (explicit escape hatch).

**Shipped defaults:**

| Limit                 | Default                  | Sizing rationale                                                                                                  |
| --------------------- | ------------------------ | ----------------------------------------------------------------------------------------------------------------- |
| `weekly_token_budget` | 10M weighted tokens/week | Dozens of tailors + daily discovery scoring with headroom; catches a runaway loop before it is a three-digit bill |
| `max_active_jobs`     | 2,000 non-archived jobs  | Guards disk/query latency, not behavior — well above a serious pipeline                                           |
| `max_concurrent_runs` | 2 per user               | One long pull + one tailor; protects the shared `llm_concurrency` pool and the single Playwright browser          |

## 5. Admin API, CLI, and web UI

**Admin API** (`/api/admin/users/*`; role check is a second dependency layered
over auth):

- Users: list (with usage summary + limits), set-role, set-limits,
  reset-password, disable/enable, delete. Delete refuses when the target is
  the last admin **or has in-flight runs**; deleting evicts and closes the
  user's engine from the registry _before_ removing the Workspace directory
  (open SQLite handles block directory removal on Windows), and requires an
  explicit confirmation flag. Deletion is admin-only — no self-service
  account deletion.
- Invites: mint (`--expires` optional), list active/used, revoke.
- System: get/set default budgets and quotas; aggregate usage view.
- Existing import/export admin endpoints stay, now operating on the whole
  data root (`system.db` + all workspaces) so the Railway backup story is
  preserved.

**Admin CLI** — `resume-agent admin <cmd>`, a thin HTTP client exactly like
vsda's `manage_users.py`: `login`, `logout`, `whoami`, `list-users`,
`invite`, `set-role`, `set-limits`, `usage [user]`, `disable`, `enable`,
`delete`. `admin login` posts username/password to the login endpoint, then
mints a PAT (named `cli`) via the PAT endpoint and caches it at
`~/.resume-agent/credentials.json`; server selected by `RESUME_AGENT_URL`.

**Web UI (React SPA):**

- **Admin page** (admins only; hidden from nav otherwise): user table (role,
  last active, 7-day usage vs budget, job count), invite minting with
  copy-to-clipboard, per-user limit editors, system-defaults panel — the
  `AdminPanel` / `UserManagementSidebar` pattern from deep-agents-ui restyled
  to the existing SPA.
- **Account page** (every user): change password, mint/revoke PATs (secret
  shown once), own usage meter, and **self-service export** —
  `GET /api/account/export` streams a `tar.gz` of the caller's own Workspace
  (same archive mechanics as the admin export, scoped to one Workspace).
  Caveat stated in the UI: the archive contains the user's `secrets.env`, so
  it is itself secret material.
- **Register page**: username / password / invite code, linked from login.
- All API additions ride the existing contract pipeline (camelCase schemas →
  `contracts/openapi.json` → generated TS client); the drift gate covers them.

## 6. Migration, local CLI, and deployment

**Legacy adoption (one-time, automatic):** on startup, if the data root has
legacy content (`profile/` or the DB file) but no `system.db`:

1. Seed the admin from `AUTH_USERNAME` / `AUTH_PASSWORD_HASH`; refuse to start
   with a clear message if they are unset (an unowned workspace must not be
   orphaned silently).
2. Move the legacy children (`db`, `profile/`, `config/`, `output/`, …) into
   `users/<admin_id>/` using the rollback-safe child-swap pattern the Railway
   admin import already uses (the mounted volume root cannot be renamed).
   Idempotent: a half-completed move resumes or rolls back.

**Local CLI compatibility:** the domain CLI (`pull`, `tailor`, `render`, …)
keeps working locally by constructing a `UserContext` directly. Resolution:
legacy-shaped root → behave exactly as today; multi-user root → default to
the sole admin's workspace, `--user <username>` to select another. This is an
**operator affordance** (the server host, or a local snapshot/export), not
how group members interact: remote members are **web-UI-only** — there is no
remote-driving transport for the domain CLI; PATs exist for scripting the
HTTP API directly and for the admin CLI. If a remote domain CLI is ever
wanted, the admin-CLI transport pattern generalizes.

**Railway:** unchanged topology — one service, one volume. `/app/data` holds
`system.db` + `users/`. Server-level LLM keys stay in service env vars;
per-user secrets live inside workspaces on the volume. Browser-only sources
keep their explicit cloud degradation, now per user.

## 7. Error handling

Typed codes through the existing `ApiException` envelope:

| Code                                                | Meaning                                                         |
| --------------------------------------------------- | --------------------------------------------------------------- |
| `INVITE_INVALID` / `INVITE_USED` / `INVITE_EXPIRED` | Registration rejected                                           |
| `BUDGET_EXCEEDED`                                   | Rolling 7-day token budget exhausted (shared-key users)         |
| `QUOTA_EXCEEDED` (429)                              | Concurrent-run cap hit (job cap reports in run summary instead) |
| `FORBIDDEN` (403)                                   | Non-admin on `/api/admin/*`                                     |
| `USER_DISABLED`                                     | Auth succeeds but account is disabled                           |
| `RATE_LIMITED` (429)                                | Failed-attempt throttle on `login` / `register`                 |

Budget/quota failures inside runs surface as failed run records with the same
codes so the SPA renders them distinctly.

## 8. Testing (offline, as always)

- Auth: register/consume-invite atomicity (two concurrent registrations, one
  code), session invalidation on password change, PAT revocation, link-token
  expiry and purpose scoping, failed-attempt rate limiter (window roll +
  reset on success), seed-only bootstrap (env rotation ignored once users
  exist).
- Tenancy isolation: two seeded users; every list endpoint returns only the
  owner's rows; one user's run/SSE stream is inaccessible to the other;
  contextvar isolation under concurrent mixed-user requests (ADR-0003).
- Budgets/quotas: synthetic `UsageEvent` rows + faked agents; own-key and
  admin exemptions; job-cap ingest behavior; concurrent-run rejection;
  failed usage write does not fail the call.
- Self-export: archive contains exactly the caller's Workspace, nothing else.
- Migration: legacy-shaped temp root → boot → admin seeded, children swapped,
  re-boot is a no-op; unset env credentials → clean startup refusal.
- Admin CLI: exercised against the app via `TestClient`-backed transport.
- Contract drift gate regenerated (`openapi.json` + TS client).

## 9. Implementation decomposition

Three sequential implementation plans, each independently green:

1. **Tenancy core + migration** — `UserContext`, engine registry, workspace
   layout, effective-Settings overlay, legacy adoption, CLI workspace
   resolution.
2. **Auth + limits** — system.db tables, register/login/PAT/link-token flows,
   budget recording + enforcement, quotas, error codes.
3. **Admin surfaces** — admin API, HTTP-client CLI, SPA admin/account/register
   pages, contract regeneration.
