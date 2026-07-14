# Workspace Data Reset — Design

**Date:** 2026-07-13
**Status:** Approved with correctness amendments (2026-07-14)

## Problem

There is no supported way to clear accumulated data. A user who wants to start
over — re-pull jobs from scratch, rebuild the profile, or hand the workspace a
clean slate — must delete files and DB rows by hand, which is error-prone
(WAL sidecars, FK order, derived caches) and impossible from the web UI.
Existing destructive paths are all narrower: `delete_job` (one zero-progress
job), `prune_run` (policy-driven archive/expire), admin `delete_user` (the
whole account), and workspace import (replace with an uploaded archive).

## Decision summary

| Decision            | Choice                                                                                                                                            |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Scopes              | Tiered: `jobs` (pipeline), `profile` (corpus + derived artifacts), `all` (both + caches)                                                          |
| What survives `all` | `config/`, `secrets.env`, and `profile/overrides.yaml` (hand-authored corrections) always; the account/login is never touched                     |
| Progressed jobs     | Deleted. Reset overrides the `has_progress` guard; the typed confirmation is the safeguard                                                        |
| Mechanism           | Table truncation through the live engine + targeted directory clearing — no engine eviction, no DB-file deletion (Windows lock-safe, mode-agnostic) |
| Surfaces            | Service function + API endpoint + CLI command + Account-page danger zone                                                                          |
| Safety UX           | API `?confirm=RESET`; CLI typed confirmation unless `--yes`; web type-to-confirm dialog with an "Export backup first" link to the existing export |
| Backup              | Never automatic; the dialog nudges toward the existing `/api/account/export`                                                                      |

## Service

New module `src/resume_agent/services/reset.py`, following the `prune.py`
use-case pattern:

```python
class ResetScope(StrEnum):
    jobs = "jobs"
    profile = "profile"
    all = "all"

def reset_workspace(
    session: Session, paths: WorkspacePaths, scope: ResetScope
) -> ResetReport: ...
```

The service receives a concrete `ResetPaths` value and never guesses deployment
layout. Multi-user callers derive it from the active `WorkspacePaths`.
Single-user API callers derive it from the app's configured `data_dir`,
`run_manager.root`, and legacy `output/` root. This distinction matters because
`create_app(data_dir=..., runs_root=...)` may not use cwd-relative defaults.
The CLI resolves the active local tenant when present and otherwise uses the
legacy flat layout.

### Scope mapping

| Scope     | DB tables cleared (in this order)                                                                | Directories/files cleared                                                                                              |
| --------- | ------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `jobs`    | `notifications`, `applications`, `cover_letters`, `resume_versions`, `skill_suggestions`, `jobs` | `output/`, `runs/`, `progress/`, `connector_runs.json` (pull telemetry; workspace root). Run-record clearing includes profile-build history — accepted as operational telemetry |
| `profile` | `skill_suggestions` only (match-gap advice derived from the profile; `notifications` hang off `applications` and are pipeline data) | enumerated `profile/` children used by the current corpus implementation: `fragments/`, `documents/` (contents), `facts.json`, `matrix.json`, `sources.json`, `cluster_map.json`; plus `taxonomy/skill_groups.json`. `overrides.yaml` and any unlisted file survive |
| `all`     | all six tables                                                                                    | union of the above + `scraper_recipes/`, `workday_facets/`                                                              |

Rules:

- Table order is children-first, extending the `delete_job_row` cascade order
  (`notifications`, `applications`, `cover_letters`, `resume_versions`, and
  other job-adjacent tables before `jobs`). All deletes commit in **one**
  transaction.
- A DB-phase exception explicitly rolls back the session before it propagates;
  no file operation starts unless the commit succeeds.
- Directories are cleared-and-recreated: contents removed, the empty
  directory kept, so downstream code never trips on a missing path.
- Directory roots and children that are symbolic links are unlinked, never
  traversed. Failures from inspection, unlinking, or recreation are collected
  exactly like deletion failures; the file phase never raises an `OSError`.
- `config/`, `secrets.env`, and `profile/overrides.yaml` are never touched by
  any scope. The profile clear is an **enumerated delete** (the listed
  children only), never "everything in the directory" — hand-authored and
  unknown future files default to surviving. Overrides are keyed by skill
  token, not fact id, so they stay valid against a rebuilt corpus.
- File removal runs **after** the DB commit succeeds. Rationale: an empty DB
  with leftover files is safe (orphans); DB rows pointing at deleted files
  would break the board.
- `ResetReport` carries `scope`, per-table deleted-row counts, successfully
  cleared areas, and `failures: dict[str, str]` (path → reason) for file-phase
  errors. `connector_runs` and `taxonomy` are explicit areas so reports and CLI
  previews do not hide file deletion behind a directory label. An area is only
  listed as cleared when all of its operations succeeded.
- No `VACUUM`: truncation leaves the DB file at its grown size (SQLite
  reuses the free pages on the next pull). Considered and accepted —
  reclaiming disk would need a separate autocommit connection and no surface
  shows file size.

## API

`POST /api/account/reset` in `api/routers/account.py`:

- Body `{ "scope": "jobs" | "profile" | "all" }` (new `CamelModel` request
  schema); query param `confirm=RESET` required, else
  `400 CONFIRM_REQUIRED` — the exact pattern of import's `confirm=REPLACE`.
- Guarded by the same active-runs check as export/import:
  `409 RUNS_ACTIVE` when `run_manager.list_active(user_id=...)` is non-empty.
- In multi-user mode, derives reset paths from the active context's
  `WorkspacePaths`. In single-user mode, derives them from the configured app
  state (`data_dir`, `run_manager.root`, and legacy `output/`). It uses the
  normal request session; truncation needs no engine eviction and has no
  multi-user-only restriction.
- Returns the `ResetReport` schema (200) even when `failures` is non-empty;
  clients surface failures as warnings. Re-running reset is idempotent and
  clears leftovers.
- OpenAPI contract regenerated (`scripts/export_openapi.py` →
  `contracts/openapi.json` → TS client); the drift gate covers the new route.

## CLI

`resume-agent reset --scope jobs|profile|all [--yes]`:

- Without `--yes`, prints what the scope will delete — current row counts per
  table (plain `SELECT COUNT(*)` before any deletion; no separate preview
  service) and every directory/file target — then requires typing the scope word to
  proceed; anything else aborts.
- Resolves paths/session through the same tenancy callback as other CLI
  commands (`--user` respected).
- Prints the `ResetReport` (rows deleted, areas cleared, failures).

## Web UI

A "Danger zone" card appended to `web/src/features/account/AccountPage.tsx`
(alongside the existing export button and `DataArchiveCard`):

- Scope picker using the installed shadcn/Base UI choice primitives with a
  short description of exactly what each clears.
- Destructive button opens a confirm dialog: shows the scope summary, an
  "Export backup first" button reusing the existing `openDownload` on
  `/api/account/export`, and a text input — the button enables only when the
  user types `RESET`.
- Changing scope or dismissing a clean dialog clears the typed confirmation so
  reopening the dialog is never pre-armed. A partial file failure deliberately
  leaves it open and armed to support the documented immediate retry.
- Clean success (`failures` empty): full page reload immediately — mirroring
  the import flow in `DataArchiveCard` — so every cached view refreshes empty
  without maintaining a cache-key list. No toast races the reload; the
  freshly empty views are the feedback.
- Failures present: **no reload** — a reload would destroy the warning
  before it renders. A warning toast ("N files left behind; run it again to
  finish") stays readable and the dialog stays open, so the user can
  immediately re-run the idempotent reset to finish the cleanup.

## Error handling

- **DB phase fails** → transaction explicitly rolls back; no files touched; standard
  error envelope. Workspace unchanged.
- **File phase fails partway** (e.g. a locked PDF on Windows) → collected
  into `ResetReport.failures`, never raised — the same philosophy as
  `FetchResult.failures`. A second reset run completes the cleanup.
- **Run started mid-reset** — the guard runs before work begins; the
  remaining race window is accepted (identical exposure to import/export).

## Testing (offline, per project convention)

- **Service** (tmp dirs + in-memory SQLite): each scope clears exactly its
  table/dir set and nothing else; `config/` + `secrets.env` +
  `profile/overrides.yaml` survive `all`;
  report counts match; second run is a no-op with zero counts; a locked/
  undeletable file lands in `failures` without raising; directories exist
  and are empty afterwards; root symlinks are not followed; a DB commit failure
  rolls back and performs no file work.
- **API**: 400 without confirm, 409 with an active run, invalid scope rejected,
  happy path per scope in multi-user mode, configured-path behavior in
  single-user mode, response shape; contract drift gate.
- **CLI**: aborts without typed confirmation; `--yes` runs; report printed.
- **Web** (Vitest): type-to-confirm gates the button; scope changes and dialog
  dismissal disarm it; the correct request is sent; a clean result reloads;
  partial failures remain visible and retryable without reloading.

## Out of scope

- Resetting `config/` or `secrets.env` (use setup/settings pages to change
  them; workspace import replaces them wholesale).
- Automatic pre-reset backups or retention of reset snapshots.
- Admin-initiated reset of another user's workspace.
- Clearing system-DB state (usage events, tokens, sessions).
