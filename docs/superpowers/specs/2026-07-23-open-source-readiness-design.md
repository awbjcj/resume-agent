# Open-Source Readiness — Design

**Date:** 2026-07-23
**Status:** Approved (design), pending implementation plan
**Goal:** Make `resume-tailor-harness` safe and feasible to publish as a public GitHub
repository: automated quality gates (CI/CD), a security pass, licensing, an
open-source-ready README, and the community-health files a public project needs.

---

## Context

`resume-tailor-harness` is a ~25.5k-line Python + React application (FastAPI backend,
Vite/React frontend, one SQLite DB) currently in a **private** GitHub repo
(`github.com/awbjcj/resume-tailor-harness`). It has **1,514 offline tests** but **no CI**,
**no LICENSE**, and **no community-health files**.

### Pre-work security audit (already performed)

The riskiest part of open-sourcing — leaked secrets in git history — is **clean**:

| Check | Result |
| --- | --- |
| `.env` tracked now or ever in history | ❌ Never tracked |
| `data/` (personal profile facts) tracked | ❌ Never tracked |
| `workspace-*.tar.gz` tracked | ❌ Never tracked (`*.tar.gz` gitignored) |
| Hardcoded API keys in tracked source | ❌ None found |
| Personal identifiers in tracked files | Only `awbjcj` (public GitHub handle) in `resume-tailor-harness-dossier.md` — already public via the repo URL, not a leak |
| Real email addresses in tracked files | ❌ None |

`.gitignore` already correctly excludes `.env`, `.env.*` (keeping
`.env.example`), `data/`, `output/`, `config/gmail_credentials.json`, browser
session profiles, and all `*.tar.gz`. `.env.example` is a correct, secret-free
template. **No history rewrite is required.**

---

## Decisions (locked)

1. **License:** MIT.
2. **Scope:** Full open-source setup (CI + Dependabot + LICENSE + all
   community-health files + README polish).
3. **Deployment from CI:** None — verify-only. Railway deploys stay manual.
4. **Security-audit gate:** Warn (non-blocking) initially.
5. **CodeQL:** Included.

---

## Architecture

The repo has two toolchains, each with its own lockfile and runner. CI mirrors
the existing `Makefile` targets exactly so local `make verify` and CI stay in
lockstep.

| Concern | Tool | Local target | Lockfile |
| --- | --- | --- | --- |
| Python deps/run | `uv` (Python 3.13) | `make setup` / `test-py` / `lint-py` | `uv.lock` |
| Python lint | `ruff check src tests evals` | `make lint-py` | — |
| Python tests | `uv run pytest tests` (fully offline; agents + Playwright faked) | `make test-py` | — |
| Web deps | `npm ci` | `make setup` | `web/package-lock.json` |
| Web lint | `eslint .` | `make lint-web` | — |
| Web tests | `vitest run` (`npm run test:run`) | `make test-web` | — |
| Web build | `tsc -b && vite build` (`npm run build`) | `make build-web` | — |

The OpenAPI contract-drift gate (`tests/api/test_openapi_contract.py`) runs as
part of the normal pytest suite — no separate CI step needed.

Evals (`make eval`) require a live API key and are **excluded** from CI.

---

## Components

### 1. CI workflow — `.github/workflows/ci.yml`

Triggers: `pull_request` → `main`, `push` → `main`.

Four independent jobs run in parallel (fail-fast off, so one red job doesn't
mask another):

- **python-quality**
  - `astral-sh/setup-uv@v6` with cache enabled
  - `uv sync --frozen`
  - `uv run ruff check src tests evals`
  - `uv run pytest tests`
- **web-quality** (`defaults.run.working-directory: web`)
  - `actions/setup-node@v4` (node 22, `cache: npm`, `cache-dependency-path: web/package-lock.json`)
  - `npm ci`
  - `npm run lint`
  - `npm run test:run`
  - `npm run build`
- **security-audit** — **non-blocking** (`continue-on-error: true`)
  - Python: `uvx pip-audit` (or `uv run pip-audit`) against the resolved env
  - Web: `npm audit --audit-level=high` (in `web/`)
- Rationale for non-blocking: an unpatchable transitive CVE must not wall off
  every merge on a brand-new public repo. Revisit as blocking once the
  dependency surface is known-clean.

Caching keeps the critical path ≤ ~5 min. Playwright browsers are **not**
installed in CI (tests fake the browser), which saves minutes.

### 2. CodeQL workflow — `.github/workflows/codeql.yml`

- `github/codeql-action` with a `python` + `javascript-typescript` matrix.
- Triggers: PRs to `main`, pushes to `main`, and a weekly `schedule` cron.
- Free for public repositories; results land in the repo Security tab.

### 3. Dependabot — `.github/dependabot.yml`

Weekly updates, `open-pull-requests-limit: 5`, for three ecosystems:
- `pip` (root `pyproject.toml` / `uv.lock`)
- `npm` (directory `/web`)
- `github-actions` (keeps the workflows' action pins current)

### 4. LICENSE

MIT text, `Copyright (c) 2026 awbjcj`.

### 5. Community-health files

- `.github/CONTRIBUTING.md` — prerequisites (`uv`, Node 22), `make setup`,
  running `make verify` before a PR, the offline-tests invariant, and the
  fact-lock rule that PRs must not weaken.
- `.github/SECURITY.md` — report privately via GitHub Security Advisories (not
  public issues); supported version = latest `main`.
- `.github/CODE_OF_CONDUCT.md` — Contributor Covenant 2.1.
- `.github/ISSUE_TEMPLATE/bug_report.md`, `feature_request.md`, and
  `config.yml`.
- `.github/pull_request_template.md` — checklist referencing `make verify`.

### 6. README polish (surgical, not a rewrite)

- Badge row at top: CI status, MIT license, Python 3.13.
- New bottom sections: **Contributing**, **Security**, **License** — each a
  short pointer to the corresponding file.
- Reframe the opening line from "A personal, command-line job-hunt pipeline" to
  make clear anyone can run it with their own profile and keys, while keeping
  the local-first / fact-lock emphasis. All existing content (funnel diagram,
  command table, architecture notes) stays.

### 7. Branch protection (manual — documented, not coded)

GitHub branch protection isn't file-configurable. Deliverable is a checklist in
`CONTRIBUTING.md` (or the final summary):
- Require the `python-quality` and `web-quality` checks to pass before merge.
- Require ≥ 1 approving review; dismiss stale approvals on new commits.
- Disallow force-pushes and deletions on `main`.

---

## Data flow (CI)

```
PR opened / push to main
        │
        ▼
 ┌──────────────┬──────────────┬────────────────┬───────────┐
 │ python-      │ web-quality  │ security-audit │ codeql    │
 │ quality      │              │ (non-blocking) │           │
 │ ruff+pytest  │ lint+test+   │ pip-audit +    │ py + js   │
 │              │ build        │ npm audit      │ analysis  │
 └──────┬───────┴──────┬───────┴────────┬───────┴─────┬─────┘
        └──── all required green ────────┘             │
                        │                        (Security tab)
                        ▼
              Mergeable (branch protection)
```

---

## Error handling

- **Flaky/failing tests:** fix the code, never skip — CI is the gate.
- **Audit finds a CVE:** surfaced in logs, does not block (by decision). Track
  via a follow-up issue if actionable.
- **Cache miss:** jobs still succeed, only slower — caches are advisory.
- **CodeQL false positive:** dismiss in the Security tab with a reason; does not
  block merge.

---

## Testing / verification

- Push the branch and confirm all four jobs appear and the three required ones
  go green on the CI run itself (the workflow is validated by running).
- `make verify` continues to pass locally (parity check).
- `LICENSE`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, and the templates render on
  GitHub (GitHub auto-detects them in the Insights → Community Standards check).

---

## Out of scope

- Git history rewriting (unnecessary — history is clean).
- Automated deployment (verify-only by decision).
- Changing application code, dependencies, or the fact-lock/tenancy invariants.
- Publishing to PyPI / npm (not requested).
- Making the repo public — that final click stays with the owner after review.

---

## Deliverables checklist

- [ ] `.github/workflows/ci.yml`
- [ ] `.github/workflows/codeql.yml`
- [ ] `.github/dependabot.yml`
- [ ] `LICENSE` (MIT)
- [ ] `.github/CONTRIBUTING.md`
- [ ] `.github/SECURITY.md`
- [ ] `.github/CODE_OF_CONDUCT.md`
- [ ] `.github/ISSUE_TEMPLATE/{bug_report.md,feature_request.md,config.yml}`
- [ ] `.github/pull_request_template.md`
- [ ] README badges + Contributing/Security/License sections + opening reframe
- [ ] Branch-protection checklist handed to owner
