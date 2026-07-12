---
repo_url: https://github.com/awbjcj/resume-agent
repo_name: resume-agent
role: sole author
generated_at: 2026-07-11
---

# Project: Resume Agent

A local-first, fact-locked AI pipeline that pulls job postings from 16+ sources, scores them against a candidate's real experience, tailors resumes and cover letters through a multi-agent review loop, renders them to PDF, and tracks applications by syncing statuses from Gmail.

## Summary

Job seekers waste hours manually rewriting a resume for each posting, and generic AI rewriters routinely fabricate experience the candidate never had. Resume Agent solves both: it ingests a person's resume (plus optional GitHub repositories) into a single `facts.json` "fact-lock," then treats that file as the only ground truth any downstream agent may draw from — agents rewrite and reframe, but a hard `fact-check` gate fails any bullet that cannot be traced to a real fact. The system is a full funnel (`pull → discover → approve → tailor → cover-letter → render → track`) exposed identically through a Typer CLI and a FastAPI + React web app over one SQLite database. It was built and maintained by a single author across 1,125 commits between 2026-06-08 and 2026-07-11 (`git shortlog`), and is actively developed: recent branches add a fast-by-default tailoring loop and a single-service Railway deployment. The codebase is ~25,500 lines of Python across 222 modules, backed by 1,514 tests that run fully offline.

## Tech stack (evidence-backed)

- Python 3.13+ — entire backend (`pyproject.toml` `requires-python = ">=3.13"`; 222 modules under `src/resume_agent/`).
- agno 2.6.x — LLM agent framework wrapped by the `AgentRunner` adapter in `src/resume_agent/llm_runner.py`.
- Anthropic / OpenAI / google-genai / DeepSeek SDKs — multi-provider LLM access behind a single `build_model()` seam in `llm_runner.py` (lazy per-provider imports).
- FastAPI + uvicorn + sse-starlette — HTTP layer with ~19 routers under `src/resume_agent/api/routers/`; long operations stream via Server-Sent Events.
- Pydantic v2 + pydantic-settings — the schema/contract source of truth (`api/schemas/base.py` `CamelModel`, fact models in `models/profile.py`).
- SQLModel over SQLite (WAL mode) — persistence; `make_engine` sets `journal_mode=WAL`, `busy_timeout`, `synchronous=NORMAL`.
- Playwright (Chromium) — real-browser automation for LinkedIn scraping, the Tesla portal, and Adzuna redirect enrichment (`discovery/scraper/`, `discovery/connectors/tesla.py`).
- Typst (`typst` Python binding) — resume and cover-letter PDF rendering from `templates/resume.typ` / `templates/cover_letter.typ`.
- React + TypeScript (Vite) — web front end, 203 `.tsx` files under `web/`, consuming a generated OpenAPI TypeScript client in `contracts/ts/`.
- markitdown (`[docx,pdf,pptx,xlsx]`) + BeautifulSoup + markdownify — resume/supporting-material ingestion and HTML→text extraction.
- Google API client + OAuth — read-only Gmail scanning for `sync-status` (`tracking/`).
- httpx — connector HTTP for every ATS/job-board backend.
- pytest + pytest-asyncio + ruff — test and lint tooling (235 test files, 1,514 test functions).

## Architecture highlights

- **Fact-lock invariant enforced by a closed schema.** Every tailored bullet must trace to `data/profile/facts.json`; the `fact-check` reviewer in `review.yaml` is a non-scored hard gate. `profile/project_extractor.py` uses a closed Pydantic boundary (`ProjectDocFacts`, `extra="forbid"`) that can emit exactly one project plus evidenced skills and *cannot* fabricate employment or education.
- **Single provider seam with lazy imports.** `build_model()` in `llm_runner.py` is the only place that knows about concrete provider SDKs; provider-prefixed model ids (`openai:` / `gemini:` / `deepseek:`, bare = Anthropic) route each of three tiers independently, so a Claude-only run never imports the OpenAI or Gemini libraries.
- **Table-driven connector dispatch with per-URL failure isolation.** `discovery/connectors/companies.py` resolves each careers URL through `detect.py` (singleton → L1 URL pattern → L2 HTML sniff) and calls the matching backend; any URL that fails detection or errors is recorded on `FetchResult.failures` and never aborts the run. 16+ ATS/board backends live in `discovery/connectors/`.
- **Workday N+1 traversal with a title gate.** `discovery/connectors/workday.py` paginates a POST list endpoint, prunes titles *before* any detail fetch, then GETs only survivors — bounded by a `_MAX_OFFSET = 1000` safety ceiling so a tenant that ignores `searchText` cannot cause unbounded fetching.
- **Deadlock-safe concurrent LLM fan-out.** Discovery and tailoring run pure-async siblings through `gather_isolated` (`concurrency.py`); a global `asyncio.Semaphore(llm_concurrency)` is acquired *only* inside the leaf `llm_runner.acall`, so nested jobs×panel fan-out cannot self-starve.
- **Thin API over a shared use-case layer.** CLI and FastAPI both call the same `services/` layer; no business logic lives in routers. Long ops return a `202` + run record worked in a threadpool where each worker opens its own DB session (`api/runs/manager.py`).
- **Contract drift is a test gate.** Pydantic → OpenAPI → generated TypeScript client (`contracts/`); `tests/api/test_openapi_contract.py` fails the build if the checked-in contract drifts from the live schema.
- **Source priority is upgrade-not-drop.** When a canonical source re-finds an aggregator job, the existing `Job` row is mutated in place (same id) so tailored resumes, cover letters, and application status are never lost; the dedup key is paired with a location guard (documented in `docs/adr/0001-dedup-key-plus-location-guard.md`).
- **LLM-as-judge evaluation with a calibration protocol.** `evals/judge.py` scores tailoring quality, but `evals/CALIBRATION.md` deliberately keeps the judge marked *untrusted* until a real human anchor (MAE < 10) is recorded — encoding evaluation rigor rather than assuming it.

## Quantified outcomes

- 1,514 test functions across 235 test files, running fully offline (LLM agents and the Playwright browser are faked; connector backends test against captured fixture JSON) — verified by `grep`/`find` over `tests/` and `README.md` "Development".
- ~25,483 lines of Python across 222 modules under `src/` (`find`/`wc` over the source tree).
- 1,125 commits from a single author between 2026-06-08 and 2026-07-11 (`git shortlog -sne`, `git rev-list --count HEAD`, `git log` date range).
- 16+ ATS/job-board connector backends (`greenhouse`, `lever`, `ashby`, `workday`, `tesla`, `google`, `smartrecruiters`, `workable`, `recruitee`, `personio`, `breezy`, `jazzhr`, `bamboohr`, `adzuna`, `remoteok`, `companies`) enumerated in `discovery/connectors/`.
- ~19 FastAPI routers (`ls src/resume_agent/api/routers/`) and 203 React `.tsx` components (`find web -name "*.tsx"`).
- Eval calibration record (`evals/CALIBRATION.md`): stand-in mean absolute error 3.4 across 5 cases, with the judge explicitly recorded as **not trusted** pending a human anchor — a documented honesty gate, not a shipped quality claim.

## Skills demonstrated

Languages: Python, TypeScript, SQL
Backend: FastAPI, REST API design, Server-Sent Events, asyncio concurrency, bounded-semaphore rate limiting, SQLModel, SQLite WAL tuning
AI / LLM engineering: multi-provider LLM orchestration (Anthropic, OpenAI, Gemini, DeepSeek), agentic pipelines with agno, multi-agent review panels, structured output via Pydantic schemas, LLM-as-judge evaluation, transient-error retry/backoff, prompt-injection-resistant extraction boundaries
Data & integration: web scraping with Playwright, ATS/portal reverse-engineering, HTML-to-text parsing, document ingestion (PDF/DOCX/PPTX via markitdown), read-only Gmail OAuth integration
Frontend: React, TypeScript, Vite, contract-first UI against a generated OpenAPI client
Architecture: domain-driven seams, dependency inversion, closed-schema invariant design, ADRs, idempotent upgrade-in-place data merges
Testing & quality: pytest, deterministic offline testing with fakes and fixtures, contract/drift tests, LLM eval harnesses, ruff linting
Tooling & delivery: Typer CLIs, Typst PDF generation, single-service Railway deployment (`docs/deploy-railway.md`, `docs/adr/0002-single-service-sqlite-volume-whole-root-custody.md`)
