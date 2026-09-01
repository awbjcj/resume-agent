# Résumé Tailor Harness — Developer Reference

## Branching

`dev` is the integration branch: all feature work branches from `dev` and
returns to `dev` by PR. `main` only ever receives merges from `dev` — never
directly from a feature branch — and is the only branch Railway deploys
from. The one exception is `hotfix/*`: a branch named `hotfix/*` may PR
directly into `main` for an urgent out-of-band fix; merge it back into `dev`
right after so `dev` doesn't drift from what's deployed. `main` is protected
(PR required, no direct pushes/force-pushes, required status checks:
`ci / python-quality`, `ci / web-quality`, `ci / security-audit`,
`require-dev-base`); the last of those
(`.github/workflows/require-dev-base.yml`) fails any PR into `main` whose
head branch isn't `dev` or `hotfix/*`, since GitHub branch protection has no
native "only allow merges from branch X (or pattern Y)" rule. Dependabot
(`.github/dependabot.yml`) targets `dev` for the same reason — dependency
bumps land on `dev` and ride the normal `dev` → `main` promotion PR like
everything else.

The repo only allows squash merging (merge commits and rebase merges are
disabled at the GitHub repo level), with a blank squash-commit message —
GitHub won't append the list of individual commits under the title. This
keeps `dev` → `main` promotion PRs, and every other PR, as one clean commit
instead of a merge commit plus an auto-generated commit-list body.

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

| Area                                                                              | Lives in                                                   |
| --------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| API layer, runs, auth, job-scoped surfaces                                        | `src/resume_tailor_harness/api/CLAUDE.md`                  |
| Core package: `llm_runner.py` provider seam, deployment, cross-cutting infra      | `src/resume_tailor_harness/CLAUDE.md`                      |
| Tenancy (ADR-0003, ADR-0009)                                                      | `src/resume_tailor_harness/tenancy/CLAUDE.md`              |
| Public network trust boundary (ADR-0008)                                          | `src/resume_tailor_harness/security/CLAUDE.md`             |
| Tailoring pipeline: fact-lock, review/scoring                                     | `src/resume_tailor_harness/tailor/CLAUDE.md`               |
| Career skill registry: hash verification, `SkillRef`, agent families              | `src/resume_tailor_harness/career_skills/registry.py`      |
| Agent prompts (registry + guidance layer)                                         | `src/resume_tailor_harness/prompts/CLAUDE.md`              |
| Rendering (template-id, Typst)                                                    | `src/resume_tailor_harness/render/CLAUDE.md`               |
| Tracking / board: archive-delete-prune, redo, dedup                               | `src/resume_tailor_harness/tracking/CLAUDE.md`             |
| Discovery pipeline: source priority, concurrency                                  | `src/resume_tailor_harness/discovery/CLAUDE.md`            |
| ATS/job-board connectors (detection, readers, Workday, Tesla/Google, pooled HTTP) | `src/resume_tailor_harness/discovery/connectors/CLAUDE.md` |
| H-1B sponsorship evidence                                                         | `src/resume_tailor_harness/h1b/CLAUDE.md`                  |
| Profile: coaching, GitHub harvest, synthesis                                      | `src/resume_tailor_harness/profile/CLAUDE.md`              |
| Skill taxonomy / skill groups                                                     | `src/resume_tailor_harness/taxonomy/CLAUDE.md`             |
| Session substrate (coach, interview, Career Lab adapters)                         | `src/resume_tailor_harness/sessions/CLAUDE.md`             |
| Career Lab                                                                        | `src/resume_tailor_harness/career_lab/CLAUDE.md`           |
| Gmail integration                                                                 | `src/resume_tailor_harness/gmail/CLAUDE.md`                |
| Calendar export (`.ics`, RFC 5545, reminder lead-time split)                      | `src/resume_tailor_harness/calendar/CLAUDE.md`             |
| Services layer: settings bundle                                                   | `src/resume_tailor_harness/services/CLAUDE.md`             |
| Agent-quality evals: how to run them, what the numbers mean                       | `evals/README.md`                                          |

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
  in `data/profile/facts.json`. Three deterministic gates decide this
  in-process before any reviewer opinion is weighed — `provenance`,
  `skill-naming`, `numeric-evidence` — and the `fact-check` reviewer is a
  hard, unscored gate on top. Their names are reserved: a `ReviewConfig`
  naming one raises. `aggregate` is the only verdict constructor, and any
  failed gate blocks the round regardless of score. Inferred skills are
  evidence pointers — they may guide emphasis but never justify a claim.
  → `tailor/CLAUDE.md`
- **Skill concentration.** A skilled task agent is one Agent family plus
  exactly one `SkillRef` resolved by `career_skills/registry.py` — models
  never choose a path, only a closed capability name. Skill bytes are
  SHA-256-verified against `skills-lock.json` inside the configured root; a
  mismatched, symlinked, or escaping entry raises `SkillUnavailable` and
  disables that capability rather than loading substituted text. The resolved
  ref is persisted with every artifact or turn it influenced.
- **Read-only tool loops.** Every tool exposed inside an agent loop is
  read-only. Writes happen after the loop, through deterministic services,
  behind user approval; anything a tool "verified" is re-verified outside the
  loop before being presented as validated. → `CONTEXT.md`
- **Source priority — upgrade, not drop.** When two sources see the same
  job, the canonical source mutates the existing `Job` row in place over an
  aggregator; user progress is never touched. → `discovery/CLAUDE.md`
- **Archive, delete, prune.** `has_progress()` (status in
  {approved, tailored, rendered} OR any ResumeVersion/CoverLetter OR an
  Application carrying _real investment_ — ADR-0013) is the single gate for
  irreversible paths; `delete_job` refuses jobs with progress. A bare `ready`
  Application does not count: opening the Tracking tab writes one
  unconditionally. → `tracking/CLAUDE.md`
- **Redo — forward-only, never destructive.** `services/redo.py` re-runs any
  stage explicitly; status never regresses, never rejects, never deletes —
  new attempts are appended under an incremented `attempt`. →
  `tracking/CLAUDE.md`

## Hot paths (most-edited files)

| Path                                                          | Role                                                                                                                      |
| ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- | ----------------- |
| `src/resume_tailor_harness/llm_runner.py`                     | `build_model` provider seam + `AgentRunner` adapter                                                                       |
| `src/resume_tailor_harness/profile/corpus.py`                 | Source registry: manifest + add/remove + legacy migration                                                                 |
| `src/resume_tailor_harness/profile/matrix.py`                 | Derived skill matrix + overrides (ban/alias/forbid/category)                                                              |
| `src/resume_tailor_harness/taxonomy/groups.py`                | Skill-group vocabulary + durable token-to-group taxonomy + delta classifier                                               |
| `src/resume_tailor_harness/profile/synthesis.py`              | Verified synthesis: deck → excerpt-backed facts (synthesize → verify → one repair round)                                  |
| `src/resume_tailor_harness/profile/fragments.py`              | Fragment cache walk: one cache/staleness policy, per-mode producers (literal, synthesis, project), concurrent production  |
| `src/resume_tailor_harness/profile/github_harvest.py`         | Deterministic GitHub project-source selection, materialization, supersession, and cleanup                                 |
| `src/resume_tailor_harness/profile/project_extractor.py`      | Project-only structured extraction that cannot emit employment or education facts                                         |
| `src/resume_tailor_harness/profile/coach.py`                  | Coach turn validation, topic-aware context, and structured-output agents                                                  |
| `src/resume_tailor_harness/profile/depth.py`                  | Evidence-owner supply, agenda seeds, and safe unmined-source question material                                            |
| `src/resume_tailor_harness/profile/aspects.py`                | Closed bullet-aspect vocabulary shared by extraction and depth measurement                                                |
| `src/resume_tailor_harness/tailor/depth.py`                   | Advisory rendered-depth measurement against the source-clamped owner plan                                                 |
| `src/resume_tailor_harness/interview/agent.py`                | Mock interviewer persona, turn/debrief validation, transcript elision                                                     |
| `src/resume_tailor_harness/services/profile_coach.py`         | Coach session turns, draft approval, recap, rebuild, and impact orchestration                                             |
| `src/resume_tailor_harness/sessions/store.py`                 | Session substrate: file custody every turn-per-run session kind rides (ADR 0006)                                          |
| `src/resume_tailor_harness/discovery/connectors/detect.py`    | ATS detection (singleton → L1 → L2)                                                                                       |
| `src/resume_tailor_harness/discovery/connectors/companies.py` | Dispatch table + per-URL fail isolation                                                                                   |
| `src/resume_tailor_harness/discovery/scraper/dashboard.py`    | Opt-in learned-recipe browser replay; cache in `data/scraper_recipes/`                                                    |
| `src/resume_tailor_harness/discovery/connectors/workday.py`   | Workday CXS list → gate → detail                                                                                          |
| `src/resume_tailor_harness/discovery/connectors/tesla.py`     | Tesla visible-browser portal: state capture + same-origin detail fetches                                                  |
| `src/resume_tailor_harness/discovery/connectors/google.py`    | Google Careers results-page `AF_initDataCallback` parser (list-only)                                                      |
| `src/resume_tailor_harness/discovery/connectors/text.py`      | Relevance gates + `html_to_text`                                                                                          |
| `src/resume_tailor_harness/discovery/connectors/runner.py`    | Pull orchestration: concurrent fetch (bounded by `pull_concurrency`), serial canonical-order ingest, `+N added` telemetry |
| `src/resume_tailor_harness/concurrency.py`                    | `gather_isolated` — ordered, error-isolated async fan-out                                                                 |
| `src/resume_tailor_harness/discovery/ingest.py`               | `save_or_upgrade`, source-priority logic                                                                                  |
| `src/resume_tailor_harness/tracking/dedup.py`                 | `compute_dedup_key` — `company                                                                                            | normalized_title` |
| `tests/test_discovery_ingest.py`                              | Ingest + dedup + priority tests                                                                                           |
| `src/resume_tailor_harness/settings_sections.py`              | Single enumeration of customizable settings: bundle scope + reset targets                                                 |
| `src/resume_tailor_harness/tracking/event_vocab.py`           | Closed event vocabularies + kind→status mapping + funnel order                                                            |
| `src/resume_tailor_harness/tracking/status_rules.py`          | Progression-vs-terminal application status (ADR-0012)                                                                     |
| `src/resume_tailor_harness/services/application_events.py`    | Timeline event validation, sequencing, status advancement                                                                 |
| `src/resume_tailor_harness/tracking/timeline_pivot.py`        | Event log → application rows; the one source for grid, CSVs, exports                                                      |
| `src/resume_tailor_harness/tracking/funnel.py`                | Sankey flow edges + median stage cycle times                                                                              |
