# Dashboard, Setup Wizard & Web Config Management — Design

**Date:** 2026-07-01
**Status:** Approved
**Branch:** feat/dashboard-setup-wizard

## 1. Goal

Make the web app self-sufficient for setup and configuration: a first-run wizard
that takes a new user from empty install to a built profile without touching the
CLI, a Settings section that can edit every config file, document import from
the browser, and a home dashboard that shows pipeline state, live runs, and
setup health at a glance.

Configs live in YAML today. A future version stores per-user configuration in
the database, so every interface here is storage-agnostic: no file paths on the
wire, stable domain names, schemas that map 1:1 to future table rows.

## 2. Decisions (resolved during design)

| Question | Decision |
| --- | --- |
| What is "the dashboard"? | A new home/overview page at `/`; existing pages keep their layouts. Shortlist moves to `/shortlist`. |
| Wizard entry | First-run gate (routed to `/setup` when setup is incomplete) + re-runnable from Settings. Steps individually editable later as settings pages. |
| Secrets over HTTP | Write-only. `GET` returns `{ key, isSet, hint }` (last-4 hint) only; values never round-trip. |
| Wizard scope | Essentials only: keys → documents → search → sources. Review/render/prune/style-guide ship with defaults and live in Settings. |
| Document model | Multi-document API (typed uploads, list/delete) designed for the profile-corpus spec; today only the `resume`-typed document feeds profile build. |
| Profile build over HTTP | Yes — becomes a Run (202 + SSE) via the existing `RunManager`. Removes the "deferred" status in CLAUDE.md for profile build. |
| Config API shape | Typed per-domain resources (`GET`/`PUT /api/config/{domain}`), full-document replace, server-side validation. |
| DB preparation | `ConfigStore` protocol seam with a YAML implementation now; DB impl is a later drop-in. No version envelope (single-user, last-write-wins). |
| Dashboard widgets | Pipeline funnel + action queue, recent runs with live status, setup/config health, quick actions. |
| Navigation | Dashboard at `/`; Settings as a sidebar entry with sub-pages; wizard at `/setup/<step>`. `/sources` redirects to `/settings/sources`. |
| Wizard commit semantics | Per step — each "Save & continue" writes that domain immediately; resume derives from setup status, no client wizard state. |
| Packaging | One spec, three implementation phases (backend → wizard/settings → dashboard), each independently green. |

## 3. Backend

### 3.1 ConfigStore seam

`services/config_store.py`:

```python
class ConfigStore(Protocol):
    def get(self, domain: str) -> BaseModel: ...
    def put(self, domain: str, model: BaseModel) -> BaseModel: ...
```

- `YamlConfigStore` is the only implementation now: a domain → (path, model
  class) map; atomic write via tmp file + `os.replace` (same pattern as
  `services/sources._save`). Missing file = model defaults (matches current
  loader behavior).
- Routers and services depend on the protocol; a future `DbConfigStore` slots
  in without touching the HTTP contract.
- Domains: `search`, `review`, `prune`, `render`, `style_guide`, `profile`
  (YAML-backed), plus `models` (env-backed — same protocol, implementation
  delegates to the `.env` merge-writer).
- Comments in hand-edited YAML are not preserved on web edit (plain
  `yaml.safe_dump`); accepted trade-off, consistent with `sources._save`.

### 3.2 Endpoints

All schemas are `CamelModel` subclasses (camelCase wire format), errors use the
existing `ApiException` envelope, and the OpenAPI → TS client is regenerated
(`bash scripts/gen_ts_client.sh`; `tests/api/test_openapi_contract.py` gates
drift).

| Endpoint | Contract |
| --- | --- |
| `GET /api/setup/status` | `{ secrets: {anthropicKey: bool, …}, profile: {documentCount, hasResume, factsBuiltAt, githubUsername}, search: {configured}, sources: {enabledCount}, complete }`. Drives the first-run gate, wizard resume, and the dashboard health card. |
| `GET/PUT /api/config/search` | Typed off the existing search config model (keywords, titles, locations, remote policy, salary, YoE, sponsorship, role anchors). |
| `GET/PUT /api/config/review` | `max_rounds`, `score_threshold`, reviewer roster (name, gate, weight, model_tier), optional length budget. |
| `GET/PUT /api/config/prune` | `fit_threshold`, `stale_days`, `retention_days`, three enable flags. |
| `GET/PUT /api/config/render` | `template_path`, `output_dir`. (Paths here are config *values*, not storage details — they stay.) |
| `GET/PUT /api/config/style-guide` | `{ content: string }` (markdown as data). |
| `GET/PUT /api/config/profile` | `{ githubUsername }`. Replaces `resume_path` usage — the document store supersedes it. |
| `GET /api/secrets` | `[{ key, isSet, hint }]`; hint = last 4 chars or null. Covers: anthropic/openai/gemini/deepseek keys, adzuna id+key, github token, linkedin email+password. |
| `GET/PUT /api/config/models` | `{ cheapModel, midModel, premiumModel }` — model tier ids are readable config, not secrets. Backed by the same `.env` merge-writer; edited on the API Keys settings page (Models section). |
| `PUT /api/secrets` | Partial map; only provided keys written (reuses `setup/env_writer` merge), `null` clears. Response is the `GET` shape. Values never echo. |
| `GET /api/profile/documents` | `[{ id, filename, docType, sizeBytes, uploadedAt }]`. |
| `POST /api/profile/documents` | Multipart: `file` + `docType` (`resume` \| `transcript` \| `portfolio` \| `other`). Validates extension (pdf/docx/txt/md) and size (≤ 15 MB) at the boundary. 201 with the document record. |
| `DELETE /api/profile/documents/{id}` | 204. |
| `POST /api/profile/build` | 202 + run record via `RunManager` (worker opens its own DB session, progress under `data/runs/`, watched at `GET /api/runs/{id}/events`). |
| `GET /api/dashboard/summary` | Read-only projection: counts per job status + action-queue counts (awaiting triage / approval / tailor / apply) + failure count of last pull. |

Deliberately **not** new: `connectors.yaml` stays behind the existing
`/api/sources` CRUD. The wizard and Settings embed that feature; there is no
second writer for the same file.

### 3.3 Document store

- Files under `data/profile/documents/{id}/{original-filename}` with a
  `data/profile/documents/manifest.json` (id, filename, docType, size,
  uploadedAt). The id is a short random slug.
- Profile build reads the `resume`-typed document (most recent if several) plus
  `githubUsername` from the profile config domain. `profile_sources.yaml`'s
  `resume_path` remains a fallback for CLI users who never upload; the web path
  supersedes it when a resume document exists.
- The profile-corpus spec (2026-07-01) consumes this same store when it lands —
  upload API and manifest shape are designed for multi-doc from day one.

### 3.4 Reuse of the TUI setup cores

The web endpoints reuse `setup/env_writer.py` (merge-write `.env`, preserving
unmanaged keys) and validation helpers from `setup/validate.py` where
applicable. The TUI wizard keeps working unchanged; both fronts write the same
files through shared cores.

## 4. Setup wizard (web)

- Route `/setup` with step routes `/setup/keys`, `/setup/documents`,
  `/setup/search`, `/setup/sources`; survives refresh, linkable per step.
- First-run gate: on load the app fetches `setup/status` once; if `complete` is
  false and the user hasn't previously exited setup (localStorage flag), route
  to `/setup`. "Exit setup" always available.
- Single-column focused layout (sidebar hidden), stepper header with four
  steps; completed steps checked and clickable. Each step commits on "Save &
  continue" (PUT/upload immediately); "Skip for now" advances without writing.
  Re-entering resumes at the first incomplete step derived from `setup/status`.
- **Step 1 — Keys:** Anthropic key prominent ("needed for tailoring"); a
  collapsed accordion holds OpenAI/Gemini/DeepSeek, Adzuna pair, GitHub token,
  LinkedIn creds. Set keys show `••••abc4` with a Replace affordance.
- **Step 2 — Documents:** drag-and-drop upload zone + document list (docType
  badge, delete); GitHub username field. Step counts as done when a
  `resume`-typed document exists.
- **Step 3 — Search:** tag inputs for keywords/titles/locations, remote-policy
  toggle group, salary/YoE numeric fields, sponsorship switch.
- **Step 4 — Sources:** embeds the existing Sources feature (URL + ATS
  auto-detect + preview, aggregator toggles).
- **Finish:** checklist from `setup/status`, then "Build profile" →
  `POST /api/profile/build` with inline SSE progress, ending in "Profile built —
  N facts extracted" → "Go to dashboard". Skipping leaves the health card
  nagging on the dashboard.

## 5. Settings section

- Sidebar gains a **Settings** entry (gear, above the footer card). `/settings`
  renders a slim secondary nav (in-page vertical list) with:
  Profile & Documents · Search · Sources · API Keys · Review panel · Rendering ·
  Pruning · Style guide.
- `/sources` redirects to `/settings/sources` (SourcesPage relocates).
- Wizard steps and settings pages share form components (e.g. one
  `SearchConfigForm`), wired to generated TS types.
- Uniform form behavior: GET → form, dirty tracking, sticky "unsaved changes"
  footer (Save / Discard), PUT on save, inline 422 field errors, toast on
  success. Last-write-wins.
- Review panel: roster as a table (name, gate switch, weight, tier select);
  fact-check row annotated "blocking — unsupported claims fail the round";
  length budget fieldset; an alert noting defaults are sensible.
- Pruning: copy adapted from the yaml comments. Style guide: monospace
  `Textarea` (new component) with char count, no preview. Profile & Documents:
  doc manager + facts status ("Built 3 days ago from 2 documents") + "Rebuild
  profile" run button with inline progress.

## 6. Dashboard

- Route `/` (Shortlist moves to `/shortlist`, stays first among work pages in
  the nav).
- **Hero:** eyebrow (`OPERATIONS · <date>`), H1 stating the actionable total
  ("6 jobs are waiting on you"), quick-action buttons reusing the exact
  run-trigger hooks behind the header's `RunActions`.
- **Action queue row:** four cards — Triage / Approve / Tailor / Apply — each
  with count + one verb, deep-linking with filters pre-applied. Zero-count
  cards render muted, never hidden (stable geography).
- **Stage rail (signature element):** horizontal strip of the seven statuses
  (raw → triage → shortlist → approved → tailored → rendered → applied) with
  live counts and thin connecting ticks. Pure CSS/flex — no recharts in the
  landing chunk (charts stay on Analytics).
- **Recent runs card:** existing run store/SSE hooks; active runs animate,
  finished show outcome + relative time.
- **Desk health card:** rendered from `setup/status`; each line links to the
  fixing settings page or wizard step. Fresh install: funnel zeros show an
  Empty state ("Add sources and run your first pull") and the health card
  dominates — the dashboard degrades into an onboarding surface.
- Data: one `GET /api/dashboard/summary` call + existing runs endpoints +
  `setup/status`.
- Visual direction: extend the existing Command Center identity (tracked
  uppercase eyebrows, operational copy, semantic tokens, quiet cards). New
  visual vocabulary is the stage rail only. Components compose the installed
  base-ui-flavored set; new additions limited to `textarea`, a tag-input
  composition (Input + Badge), and a native drag-drop zone styled like `Empty`.

## 7. Error handling

- Config PUTs: Pydantic validation at the boundary → 422 with field details in
  the standard envelope; forms map details to inline field errors.
- Uploads: 422 for type/size violations; storage failures 500 with generic
  message. Partial upload never registers in the manifest (write file first,
  manifest last, atomic replace).
- Secrets: malformed keys rejected 422; `.env` write failures 500 and no
  partial writes (merge-write is atomic via tmp + replace).
- Profile build failures surface through the run record (existing failure
  telemetry); wizard finish screen shows the failure with a retry button.
- Setup gate fail-open: if `setup/status` errors, the app loads normally
  (never lock the user out of a working dashboard because one endpoint broke).

## 8. Testing

- Offline suite as always (no network, agents faked).
- Backend: unit tests per config domain (get default / put valid / put invalid
  422 / round-trip), secrets write-only behavior (GET never contains values),
  upload validation + manifest atomicity, setup-status projection, dashboard
  summary counts against seeded DB, profile-build run registration (LLM faked).
- Contract: OpenAPI drift gate extended to the new routes.
- Frontend: vitest component tests for wizard step commit/skip/resume logic,
  settings dirty-state/save flows, dashboard rendering against mocked client;
  Playwright smoke for the first-run gate → wizard → dashboard happy path.

## 9. Implementation phases

1. **Backend contract** — ConfigStore seam, config/secrets/setup-status
   routers, document store + upload, profile-build run, dashboard summary,
   OpenAPI + TS regen. CLI/TUI untouched.
2. **Wizard + Settings** — settings routes and shared forms, wizard shell +
   four steps + finish screen, first-run gate, Sources relocation.
3. **Dashboard** — summary endpoint consumption, hero + queue + stage rail +
   runs + health cards, route shuffle (`/` → dashboard, Shortlist →
   `/shortlist`).

Each phase lands independently green (suite + `ruff check` + contract gate).
