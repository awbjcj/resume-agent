# Resume Agent — Developer Reference

## Branching

`main` is currently the only branch on `origin`; feature work branches from it
and returns by PR. `main` is protected (PR + passing checks required, no direct
pushes/force-pushes) and is the only branch Railway deploys from. If an integration
branch is reintroduced, update this section and the CI branch triggers together.

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

## Architecture map

This file stays intentionally short. Every subsystem's detailed design notes —
the "why", the gotchas, the measured numbers — live in a nested `CLAUDE.md`
that Claude auto-discovers once you're working inside that directory. Read
the linked file before touching that area; don't duplicate its content back
into this one.

| Area                                                                              | Lives in                                          |
| --------------------------------------------------------------------------------- | ------------------------------------------------- |
| API layer, runs, auth, job-scoped surfaces                                        | `src/resume_agent/api/CLAUDE.md`                  |
| Core package: `llm_runner.py` provider seam, deployment, cross-cutting infra      | `src/resume_agent/CLAUDE.md`                      |
| Tenancy (ADR-0003, ADR-0009)                                                      | `src/resume_agent/tenancy/CLAUDE.md`              |
| Public network trust boundary (ADR-0008)                                          | `src/resume_agent/security/CLAUDE.md`             |
| Tailoring pipeline: fact-lock, review/scoring                                     | `src/resume_agent/tailor/CLAUDE.md`               |
| Agent prompts (registry + guidance layer)                                         | `src/resume_agent/prompts/CLAUDE.md`              |
| Rendering (template-id, Typst)                                                    | `src/resume_agent/render/CLAUDE.md`               |
| Tracking / board: archive-delete-prune, redo, dedup                               | `src/resume_agent/tracking/CLAUDE.md`             |
| Discovery pipeline: source priority, concurrency                                  | `src/resume_agent/discovery/CLAUDE.md`            |
| ATS/job-board connectors (detection, readers, Workday, Tesla/Google, pooled HTTP) | `src/resume_agent/discovery/connectors/CLAUDE.md` |
| H-1B sponsorship evidence                                                         | `src/resume_agent/h1b/CLAUDE.md`                  |
| Profile: coaching, GitHub harvest, synthesis                                      | `src/resume_agent/profile/CLAUDE.md`              |
| Skill taxonomy / skill groups                                                     | `src/resume_agent/taxonomy/CLAUDE.md`             |
| Session substrate (coach, interview, Career Lab adapters)                         | `src/resume_agent/sessions/CLAUDE.md`             |
| Career Lab                                                                        | `src/resume_agent/career_lab/CLAUDE.md`           |
| Gmail integration                                                                 | `src/resume_agent/gmail/CLAUDE.md`                |
| Services layer: settings bundle                                                   | `src/resume_agent/services/CLAUDE.md`             |
| Agent-quality evals: how to run them, what the numbers mean                       | `evals/README.md`                                 |

## Core invariants (never break these)

These are the rules that must never be violated, anywhere in the codebase.
Full rationale and enforcement detail lives in the linked file — read it
before changing code near the invariant.

- **Tenancy context (ADR-0003).** Multi-user state rides one
  `contextvars.ContextVar` holding the active `UserContext`; `get_settings()`
  must never be cached across requests. → `tenancy/CLAUDE.md`
- **Public network trust boundary (ADR-0008).** Every user-influenced fetch,
  download, render, or archive import goes through `security/outbound.py`'s
  single egress gateway; download routes stay tenant-confined via
  `tenancy/storage.py::artifact_path`; archive extraction is
  resource-bounded, not just path-validated. → `security/CLAUDE.md`
- **Registration modes and spend governance (ADR-0009).** Shared-key spend is
  resolved once per phase by `tenancy/spend.py`'s `SpendGate`; admins are
  exempt from the per-user allowance but remain bound by the platform-wide
  monthly cap. → `tenancy/CLAUDE.md`
- **Fact-lock.** Every bullet on a tailored resume must trace back to a fact
  in `data/profile/facts.json`; the `fact-check` reviewer is a hard,
  unscored gate. Inferred skills are evidence pointers — they may guide
  emphasis but never justify a claim. → `tailor/CLAUDE.md`
- **Source priority — upgrade, not drop.** When two sources see the same
  job, the canonical source mutates the existing `Job` row in place over an
  aggregator; user progress is never touched. → `discovery/CLAUDE.md`
- **Archive, delete, prune.** `has_progress()` (status in
  {approved, tailored, rendered} OR any Application/ResumeVersion/CoverLetter)
  is the single gate for irreversible paths; `delete_job` refuses jobs with
  progress. → `tracking/CLAUDE.md`
- **Redo — forward-only, never destructive.** `services/redo.py` re-runs any
  stage explicitly; status never regresses, never rejects, never deletes —
  new attempts are appended under an incremented `attempt`. →
  `tracking/CLAUDE.md`

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
| `src/resume_agent/profile/depth.py`                  | Evidence-owner supply, agenda seeds, and safe unmined-source question material                                            |
| `src/resume_agent/profile/aspects.py`                | Closed bullet-aspect vocabulary shared by extraction and depth measurement                                                |
| `src/resume_agent/tailor/depth.py`                   | Advisory rendered-depth measurement against the source-clamped owner plan                                                 |
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
