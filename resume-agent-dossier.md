---
repo_url: https://github.com/awbjcj/resume-agent
repo_name: resume-agent
role: sole author
generated_at: 2026-08-29
---

# Project: Resume Agent

A fact-locked job-search platform for discovering roles, tailoring application materials, practicing interviews, and tracking the complete application lifecycle.

## Summary

Resume Agent turns resumes and supporting documents into a closed-schema evidence profile, then uses that profile to score jobs and generate resumes and cover letters without inventing experience. It exposes one job-search funnel through a Typer CLI and a FastAPI and React web application, with per-user workspaces for hosted deployments. The platform also supports conversational coaching, mock interviews, cited employer research, application-event timelines, analytics, calendar and CSV exports, and Gmail-assisted status tracking. The repository remains under active development and is maintained by its sole human author.

Role: sole author (2,012 of 2,070 commits across two author identities; 58 bot commits, `git shortlog -sne HEAD`)
Repository: https://github.com/awbjcj/resume-agent
Timeline: 2026-06 – present (`git log --reverse --format=%as`; `git log -1 --format=%as`)

## Tech stack (evidence-backed)

- Python — 418 backend modules under `src/resume_agent/`; the project requires Python 3.13 or newer in `pyproject.toml`.
- TypeScript — the React application and generated API client under `web/src/` and `contracts/ts/`.
- SQL — grouped, filtered, and paged persistence queries in `src/resume_agent/tracking/board_query.py`, `src/resume_agent/tracking/timeline_pivot.py`, and `src/resume_agent/tenancy/`.
- FastAPI — 45 router modules under `src/resume_agent/api/routers/` expose the web and integration APIs.
- Pydantic — closed extraction schemas, API contracts, and settings validation under `src/resume_agent/models/`, `src/resume_agent/api/schemas/`, and `src/resume_agent/config.py`.
- SQLModel — domain tables and session-backed services in `src/resume_agent/tracking/tables.py`, `src/resume_agent/tenancy/`, and `src/resume_agent/services/`.
- SQLite — WAL-mode workspace databases and a separate hosted system database configured by `src/resume_agent/db.py` and `src/resume_agent/tenancy/system_db.py`.
- Agno — model-agent execution is isolated behind `src/resume_agent/llm_runner.py::AgentRunner` and task-specific `agents.py` modules.
- Anthropic API — bare model identifiers route through the provider seam in `src/resume_agent/llm_routing.py` and `src/resume_agent/llm_runner.py`.
- OpenAI API — `openai:` models, embeddings, transcription, and speech route through `src/resume_agent/llm_routing.py` and `src/resume_agent/llm_runner.py`.
- Google Gemini API — `gemini:` models route through `src/resume_agent/llm_routing.py` and `src/resume_agent/llm_runner.py`.
- DeepSeek API — `deepseek:` models route through `src/resume_agent/llm_routing.py` and `src/resume_agent/llm_runner.py`.
- Model Context Protocol — a prefixed read-only H-1B toolset is confined to `src/resume_agent/h1b/mcp.py` and the sponsorship agents in `src/resume_agent/h1b/service.py`, as recorded by ADR 0011.
- Server-Sent Events — resumable run and conversational streams are implemented in `src/resume_agent/api/routers/runs.py` and `src/resume_agent/sessions/stream.py`.
- React — 399 `.tsx` modules under `web/src/` implement the browser application.
- Vite — frontend development and production builds are defined in `web/package.json` and `web/vite.config.ts`.
- TanStack Query — API cache and mutation orchestration throughout `web/src/features/`.
- i18next — English and Simplified Chinese runtime localization in `web/src/i18n/`.
- Tailwind CSS — design tokens and utility styling configured by `web/src/index.css` and the Vite plugin.
- Typer — the command-line surface begins in `src/resume_agent/cli.py`.
- Typst — resume and cover-letter PDF rendering uses `templates/*.typ` and `src/resume_agent/render/`.
- Playwright — browser-backed connectors and browser regression coverage live in `src/resume_agent/discovery/scraper/`, `src/resume_agent/discovery/connectors/tesla.py`, and `web/e2e/`.
- httpx — connector HTTP, provider-adjacent calls, and the guarded outbound gateway use `httpx` under `src/resume_agent/discovery/connectors/` and `src/resume_agent/security/outbound.py`.
- Gmail API — per-user inbox reads and draft creation are implemented under `src/resume_agent/gmail/` and `src/resume_agent/api/routers/gmail.py`.
- OpenAPI — the committed backend contract and generated TypeScript client live in `contracts/openapi.json` and `contracts/ts/api.ts`.
- API design — typed REST resources and a generated client share the contract in `src/resume_agent/api/schemas/`, `src/resume_agent/api/routers/`, and `contracts/`.
- Multi-tenant architecture — hosted requests, runs, storage, databases, and settings are scoped through `src/resume_agent/tenancy/`.
- asyncio — LLM and connector fan-out is bounded in `src/resume_agent/concurrency.py`, `src/resume_agent/llm_runner.py`, and `src/resume_agent/discovery/connectors/runner.py`.
- Schema design — closed profile facts, application events, API envelopes, and agent outputs use explicit models under `src/resume_agent/models/` and `src/resume_agent/api/schemas/`.
- Security engineering — the threat model, guarded egress, archive validation, authentication, and tenant storage controls live in `docs/resume-agent-threat-model.md`, `src/resume_agent/security/`, and `src/resume_agent/tenancy/storage.py`.
- pytest — Python tests live under `tests/` and `evals/`.
- Vitest — React unit and integration tests are configured in `web/package.json` and colocated under `web/src/`.
- Ruff — the Python lint contract is declared in `pyproject.toml`.
- GitHub Actions — CI workflows are checked in under `.github/workflows/`.
- Railway — the single-service deployment, persistent-volume custody, and production settings are documented in `Dockerfile`, `railway.json`, and `docs/deploy-railway.md`.

## Architecture highlights

- Enforced fact-locked generation by combining closed Pydantic extraction schemas with deterministic provenance and fact-check gates, preventing project sources from emitting employment or education and rejecting unsupported tailored claims — `src/resume_agent/profile/project_extractor.py`, `src/resume_agent/tailor/provenance.py`, `src/resume_agent/tailor/workflow.py`, `src/resume_agent/tailor/verdict.py`.
- Isolated hosted users with a request-scoped workspace context, separate SQLite databases, and tenant-confined artifact resolution so request, background-run, and CLI paths share one custody model — `src/resume_agent/tenancy/context.py`, `src/resume_agent/tenancy/storage.py`, ADR 0003.
- Secured user-influenced retrieval behind one DNS-rebinding-resistant httpx gateway that validates every redirect, pins the validated address, and bounds response type and size — `src/resume_agent/security/outbound.py`, ADR 0008.
- Engineered a provider-neutral Agno streaming substrate whose durable event log supports resumable Server-Sent Events, cooperative cancellation, and shared React chat primitives across coaching, interviews, discovery, and Career Lab — `src/resume_agent/llm_runner.py`, `src/resume_agent/sessions/stream.py`, `src/resume_agent/sessions/turns.py`, `web/src/components/chat/`.
- Consolidated 13 ATS-specific company adapters behind table-driven detection and per-URL failure isolation, then registered them alongside company-URL, recipe-scrape, Adzuna, RemoteOK, and LinkedIn connectors so one malformed source cannot abort a pull — `src/resume_agent/discovery/connectors/companies.py`, `src/resume_agent/discovery/connectors/registry.py`.
- Built a canonical SQLModel application-event dataset that drives the cross-job grid, wide and lossless CSV exports, calendar downloads, funnel analytics, cycle times, and offer comparisons without independent projections drifting — `src/resume_agent/tracking/timeline_pivot.py`, `src/resume_agent/api/routers/applications.py`, `src/resume_agent/api/routers/calendar.py`, `src/resume_agent/api/routers/analytics.py`.
- Hardened cited company intelligence through an explicit-refresh Agno research and formatting pair that accepts only source URLs present in the research output, preserves the last good SQLite record on failure, and shares evidence by normalized company — `src/resume_agent/company_intelligence/agents.py`, `src/resume_agent/services/company_intelligence.py`, `src/resume_agent/tracking/tables.py`.
- Preserved asynchronous outcomes beyond Server-Sent Events by recording idempotent terminal run history, while workspace-scoped saved views restore canonical URL filter state and dashboard projections surface practice and source-health trends — `src/resume_agent/services/run_completions.py`, `src/resume_agent/services/board_views.py`, `src/resume_agent/services/dashboard.py`.

## Quantified outcomes

- Defined 3,369 Python test functions across 446 files (`rg -n '^\s*(async\s+)?def\s+test_' tests evals`; `rg -l '^\s*(async\s+)?def\s+test_' tests evals`).
- Implemented 74,143 physical lines of Python across 418 modules under `src/resume_agent/` (PowerShell `rg --files src/resume_agent -g '*.py'` plus `Get-Content` line counts).
- Shipped 45 FastAPI router modules and 399 React `.tsx` modules (`rg --files src/resume_agent/api/routers -g '*.py'`, excluding `__init__.py`; `rg --files web/src -g '*.tsx'`).
- Maintained 2,070 commits from 2026-06-08 through 2026-08-29, with 2,012 attributed to the same human across two identities and 58 to bots (`git rev-list --count HEAD`; `git shortlog -sne HEAD`).
- Registered 18 connector kinds, including 13 ATS-specific adapters plus company-URL, recipe-scrape, Adzuna, RemoteOK, and LinkedIn source families (`src/resume_agent/discovery/connectors/companies.py`, `src/resume_agent/discovery/connectors/registry.py`).
- Recorded 13 accepted architecture decisions covering deduplication, custody, tenancy, agent write boundaries, filtering, security, quotas, MCP isolation, and application-status invariants (`docs/adr/README.md`).

## Skills demonstrated

Languages: Python, TypeScript, SQL
Frameworks: FastAPI, Pydantic, SQLModel, Agno, React, Vite, Typer
Databases: SQLite
AI & APIs: Anthropic API, OpenAI API, Google Gemini API, DeepSeek API, Model Context Protocol, Gmail API
Frontend: TanStack Query, i18next, Tailwind CSS, Server-Sent Events
Testing: pytest, Vitest, Playwright
Architecture: API design, Multi-tenant architecture, asyncio, Schema design, Security engineering
Tooling: httpx, OpenAPI, Typst, Ruff, GitHub Actions, Railway
