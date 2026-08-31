---
repo_url: https://github.com/awbjcj/resume-tailor-harness
repo_name: resume-tailor-harness
role: sole author
generated_at: 2026-08-30
---

# Project: Résumé Tailor Harness

An agent harness that makes résumé tailoring end-to-end and controllable: every model output must clear a deterministic gate before it becomes a durable artifact, and every irreversible step belongs to the user.

## Summary

Résumé Tailor Harness is an agent harness built around one constraint — a language model may draft, reframe, and critique, but it may never be the last authority on what reaches a document. The harness enforces that with three layers of engineering. **Fact-lock** turns a candidate's real history into a closed-schema evidence profile and refuses any generated claim that cannot cite a fact id in it, checked in-process before an LLM reviewer is ever paid. **Skill-concentrated tailoring** binds each task agent to exactly one SHA-256-verified local `SKILL.md` procedure resolved through a root-confined registry, so the procedure a model runs is an identified, persisted, tamper-evident artifact rather than an ambient prompt. **Bounded tool loops** keep every in-loop tool read-only, moving all writes to deterministic services behind user approval.

On top of that harness sits a complete job-application workflow: multi-source job discovery, fit scoring, a reviewer-panel tailoring loop, fact-locked cover letters, Typst PDF rendering, mock interviews, profile coaching, cited employer research, H-1B sponsorship evidence, and an application-event timeline with analytics and calendar export. It runs as a Typer CLI, a FastAPI and React web application, or a hosted multi-user service with per-user workspaces. The repository remains under active development and is maintained by its sole human author.

Role: sole author (2,059 of 2,117 commits across two author identities; 58 bot commits, `git shortlog -sne HEAD`)
Repository: https://github.com/awbjcj/resume-tailor-harness
Timeline: 2026-06 – present (`git log --reverse --format=%as`; `git log -1 --format=%as`)

## Tech stack (evidence-backed)

- Python — 437 backend modules under `src/resume_tailor_harness/`; the project requires Python 3.13 or newer in `pyproject.toml`.
- TypeScript — the React application and generated API client under `web/src/` and `contracts/ts/`.
- SQL — grouped, filtered, and paged persistence queries in `src/resume_tailor_harness/tracking/board_query.py`, `src/resume_tailor_harness/tracking/timeline_pivot.py`, and `src/resume_tailor_harness/tenancy/`.
- FastAPI — 48 router modules under `src/resume_tailor_harness/api/routers/` expose the web and integration APIs.
- Pydantic — closed extraction schemas, agent output contracts, API contracts, and settings validation under `src/resume_tailor_harness/models/`, `src/resume_tailor_harness/api/schemas/`, and `src/resume_tailor_harness/config.py`.
- SQLModel — domain tables and session-backed services in `src/resume_tailor_harness/tracking/tables.py`, `src/resume_tailor_harness/tenancy/`, and `src/resume_tailor_harness/services/`.
- SQLite — WAL-mode workspace databases and a separate hosted system database configured by `src/resume_tailor_harness/db.py` and `src/resume_tailor_harness/tenancy/system_db.py`.
- Agno — model-agent execution is isolated behind `src/resume_tailor_harness/llm_runner.py::AgentRunner` and task-specific `agents.py` modules.
- Agent harness design — the skill registry, agent-family boundary, deterministic gate set, verdict constructor, and read-only tool-loop rule live in `src/resume_tailor_harness/career_skills/registry.py`, `src/resume_tailor_harness/tailor/verdict.py`, `src/resume_tailor_harness/tailor/workflow.py`, and `CONTEXT.md`.
- Prompt engineering — least-privilege reviewer inputs, untrusted-content delimiting, and reviewer-identity validation are implemented in `src/resume_tailor_harness/tailor/panel.py` and `src/resume_tailor_harness/tailor/prompt_blocks.py`.
- LLM evaluation — a judge, calibration set, metrics, and reporting for tailoring and cover-letter quality live under `evals/`.
- Anthropic API — bare model identifiers route through the provider seam in `src/resume_tailor_harness/llm_routing.py` and `src/resume_tailor_harness/llm_runner.py`.
- OpenAI API — `openai:` models, embeddings, transcription, and speech route through `src/resume_tailor_harness/llm_routing.py` and `src/resume_tailor_harness/llm_runner.py`.
- Google Gemini API — `gemini:` models route through `src/resume_tailor_harness/llm_routing.py` and `src/resume_tailor_harness/llm_runner.py`.
- DeepSeek API — `deepseek:` models route through `src/resume_tailor_harness/llm_routing.py` and `src/resume_tailor_harness/llm_runner.py`.
- Model Context Protocol — a prefixed read-only H-1B toolset is confined to `src/resume_tailor_harness/h1b/mcp.py` and the sponsorship agents in `src/resume_tailor_harness/h1b/service.py`, as recorded by ADR 0011.
- Server-Sent Events — resumable run and conversational streams are implemented in `src/resume_tailor_harness/api/routers/runs.py` and `src/resume_tailor_harness/sessions/stream.py`.
- React — 406 `.tsx` modules under `web/src/` implement the browser application.
- Vite — frontend development and production builds are defined in `web/package.json` and `web/vite.config.ts`.
- TanStack Query — API cache and mutation orchestration throughout `web/src/features/`.
- i18next — English and Simplified Chinese runtime localization in `web/src/i18n/`.
- Tailwind CSS — design tokens and utility styling configured by `web/src/index.css` and the Vite plugin.
- Typer — the command-line surface begins in `src/resume_tailor_harness/cli.py`.
- Typst — resume and cover-letter PDF rendering uses `templates/*.typ` and `src/resume_tailor_harness/render/`.
- Playwright — browser-backed connectors and browser regression coverage live in `src/resume_tailor_harness/discovery/scraper/`, `src/resume_tailor_harness/discovery/connectors/tesla.py`, and `web/e2e/`.
- httpx — connector HTTP, provider-adjacent calls, and the guarded outbound gateway use `httpx` under `src/resume_tailor_harness/discovery/connectors/` and `src/resume_tailor_harness/security/outbound.py`.
- Gmail API — per-user inbox reads and draft creation are implemented under `src/resume_tailor_harness/gmail/` and `src/resume_tailor_harness/api/routers/gmail.py`.
- OpenAPI — the committed backend contract and generated TypeScript client live in `contracts/openapi.json` and `contracts/ts/api.ts`.
- API design — typed REST resources and a generated client share the contract in `src/resume_tailor_harness/api/schemas/`, `src/resume_tailor_harness/api/routers/`, and `contracts/`.
- Multi-tenant architecture — hosted requests, runs, storage, databases, and settings are scoped through `src/resume_tailor_harness/tenancy/`.
- asyncio — LLM and connector fan-out is bounded in `src/resume_tailor_harness/concurrency.py`, `src/resume_tailor_harness/llm_runner.py`, and `src/resume_tailor_harness/discovery/connectors/runner.py`.
- Schema design — closed profile facts, application events, API envelopes, and agent outputs use explicit models under `src/resume_tailor_harness/models/` and `src/resume_tailor_harness/api/schemas/`.
- Security engineering — the threat model, guarded egress, archive validation, authentication, and tenant storage controls live in `docs/resume-tailor-harness-threat-model.md`, `src/resume_tailor_harness/security/`, and `src/resume_tailor_harness/tenancy/storage.py`.
- pytest — Python tests live under `tests/` and `evals/`.
- Vitest — React unit and integration tests are configured in `web/package.json` and colocated under `web/src/`.
- Ruff — the Python lint contract is declared in `pyproject.toml`.
- GitHub Actions — CI workflows are checked in under `.github/workflows/`.
- Railway — the single-service deployment, persistent-volume custody, and production settings are documented in `Dockerfile`, `railway.json`, and `docs/deploy-railway.md`.

## Architecture highlights

- Enforced fact-locked generation by pairing closed Pydantic extraction schemas with three in-process deterministic gates — provenance, skill-naming, and numeric-evidence — whose names are reserved so a user-configured reviewer can never shadow a gate, and routed every gate and reviewer critique through a single verdict constructor so "what makes a round pass" has one shape — `src/resume_tailor_harness/tailor/verdict.py`, `src/resume_tailor_harness/tailor/review_config.py`, `src/resume_tailor_harness/tailor/provenance.py`, `src/resume_tailor_harness/profile/project_extractor.py`.
- Concentrated every skilled task agent onto exactly one approved procedure by building a root-confined, SHA-256-verified registry that resolves a closed skill name to an immutable `SkillRef` — models never choose a path, a symlinked or altered entry disables that capability instead of loading substituted text, and the resolved ref is persisted with every artifact and turn the skill influenced — `src/resume_tailor_harness/career_skills/registry.py`, `src/resume_tailor_harness/career_skills/models.py`, `skills-lock.json`.
- Made the review loop cost-aware through control flow rather than prompt text: mechanically provable gates run before the paid reviewer panel so their issues reach the reviser in the round they were made, a provenance-only failure earns a free retry outside the `max_rounds` quality budget, each revision builds from the best gate-clean round instead of the latest one, and a scored regression stops the loop early — `src/resume_tailor_harness/tailor/workflow.py`.
- Applied least privilege to prompts by giving gate reviewers only the profile facts a draft actually cites and advisory reviewers no raw profile at all, delimiting every third-party job description as untrusted content, validating that a critique claims the reviewer identity it was asked for, and requiring a merged advisory panel to cover exactly its configured roster — `src/resume_tailor_harness/tailor/panel.py`, `src/resume_tailor_harness/tailor/prompt_blocks.py`.
- Bounded model autonomy to read-only tool loops across Source Scout, Profile Coach, sponsorship research, and Career Lab — proposals, draft notes, and candidate sources are re-verified outside the loop and become writes only through deterministic services on user approval, keeping Career Lab output draft-only by construction — `src/resume_tailor_harness/career_lab/`, `src/resume_tailor_harness/discovery/`, `src/resume_tailor_harness/h1b/service.py`, ADR 0011.
- Engineered a provider-neutral Agno substrate in which one model seam turns a provider-prefixed id into a model with lazily imported SDKs, three cost tiers can mix providers freely, and a durable event log supports resumable Server-Sent Events, cooperative cancellation, idempotent terminal run history, and shared React chat primitives — `src/resume_tailor_harness/llm_routing.py`, `src/resume_tailor_harness/llm_runner.py`, `src/resume_tailor_harness/sessions/stream.py`, `src/resume_tailor_harness/services/run_completions.py`.
- Isolated hosted users with a request-scoped workspace context, separate SQLite databases, and tenant-confined artifact resolution so request, background-run, and CLI paths share one custody model, and secured user-influenced retrieval behind a DNS-rebinding-resistant httpx gateway that validates every redirect and pins the validated address — `src/resume_tailor_harness/tenancy/context.py`, `src/resume_tailor_harness/tenancy/storage.py`, `src/resume_tailor_harness/security/outbound.py`, ADR 0003, ADR 0008.
- Consolidated 13 ATS-specific company adapters behind table-driven detection and per-URL failure isolation, then built a canonical SQLModel application-event dataset that drives the cross-job grid, wide and lossless CSV exports, calendar downloads, funnel analytics, and offer comparisons without independent projections drifting — `src/resume_tailor_harness/discovery/connectors/companies.py`, `src/resume_tailor_harness/discovery/connectors/registry.py`, `src/resume_tailor_harness/tracking/timeline_pivot.py`, `src/resume_tailor_harness/api/routers/analytics.py`.

## Quantified outcomes

- Defined 3,411 Python test functions across 454 files (`grep -rhE '^\s*(async )?def test_' tests evals`; `grep -rlE '^\s*(async )?def test_' tests evals`).
- Implemented 76,403 physical lines of Python across 437 modules under `src/resume_tailor_harness/` (`find src/resume_tailor_harness -name '*.py'`).
- Registered 35 hash-verified career skills spanning 8 agent families in the approved skill manifest, each pinned to a reviewed upstream ref and SHA-256 digest (`skills-lock.json`; `src/resume_tailor_harness/career_skills/models.py::AgentFamily`).
- Shipped 48 FastAPI router modules and 406 React `.tsx` modules (`ls src/resume_tailor_harness/api/routers/*.py`, excluding `__init__.py`; `find web/src -name '*.tsx'`).
- Maintained 2,117 commits from 2026-06-08 through 2026-08-30, with 2,059 attributed to the same human across two identities and 58 to bots (`git rev-list --count HEAD`; `git shortlog -sne HEAD`).
- Registered 18 connector kinds, including 13 ATS-specific adapters plus company-URL, recipe-scrape, Adzuna, RemoteOK, and LinkedIn source families (`src/resume_tailor_harness/discovery/connectors/companies.py`, `src/resume_tailor_harness/discovery/connectors/registry.py`).
- Recorded 13 accepted architecture decisions covering deduplication, custody, tenancy, agent write boundaries, filtering, security, quotas, MCP isolation, and application-status invariants (`docs/adr/README.md`).

## Skills demonstrated

Languages: Python, TypeScript, SQL
Frameworks: FastAPI, Pydantic, SQLModel, Agno, React, Vite, Typer
Databases: SQLite
AI & APIs: Agent harness design, Prompt engineering, LLM evaluation, Anthropic API, OpenAI API, Google Gemini API, DeepSeek API, Model Context Protocol, Gmail API
Frontend: TanStack Query, i18next, Tailwind CSS, Server-Sent Events
Testing: pytest, Vitest, Playwright
Architecture: API design, Multi-tenant architecture, asyncio, Schema design, Security engineering
Tooling: httpx, OpenAPI, Typst, Ruff, GitHub Actions, Railway
