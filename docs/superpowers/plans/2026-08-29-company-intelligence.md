# Company Intelligence — Implementation Plan

**Goal:** Add a durable, source-backed company dossier to each job, refreshed only on explicit request and reusable by interview preparation.

**Architecture:** Company facts are cached by normalized employer name in one canonical table. A two-stage research pipeline searches the web, then projects only grounded URLs and claims into a typed dossier. Job detail exposes the shared dossier with a server-owned stale flag; the web app renders it in a dedicated Research tab and launches refreshes through the existing Run/SSE path. New interview sessions snapshot the dossier alongside the JD and submitted resume, so later refreshes never rewrite interview history.

**Reference patterns:** The design adapts `ai-job-search`'s durable company-research cache and verify-before-use rule plus `career-ops`'s research axes (strategy, recent moves, engineering culture, challenges, and competitive position). It deliberately does not duplicate this repository's existing H-1B evidence, match-gap resources, reminders, email sync, or mock-interview UI.

## Global constraints

- Branch: `feature/company-intelligence`, based on `main`.
- Existing H-1B cache semantics remain unchanged: expired evidence renders stale and never refreshes automatically.
- Company intelligence follows the same explicit-refresh rule. Reading job detail must never call a provider or an LLM.
- Search output is untrusted data. The formatter cannot search, and the server drops every source or claim citation whose normalized URL is absent from the search transcript.
- Company-wide facts must not contain role-specific candidate claims. Job- and candidate-specific framing remains a downstream consumer concern.
- API models use `CamelModel`; regenerate OpenAPI and both TypeScript clients after schema changes.
- Background work owns its own database session and uses a company-scoped singleton key.
- Tests run without network access by injecting fake research and formatter runners.

## Slice 1 — Canonical evidence and grounding

**Files:**

- Create `src/resume_agent/company_intelligence/models.py`
- Create `src/resume_agent/company_intelligence/agents.py`
- Create `src/resume_agent/services/company_intelligence.py`
- Modify `src/resume_agent/tracking/tables.py`
- Modify `src/resume_agent/config.py`
- Modify `src/resume_agent/prompts/registry.py`
- Add focused model/service tests

**Contract:**

- Five closed research axes: `strategy`, `recent_moves`, `engineering_culture`, `challenges`, `competitive_position`.
- Every insight has a non-empty summary and at least one citation.
- Every persisted citation refers to a persisted HTTP(S) source copied exactly from grounded research.
- One `company_intelligence_evidence` row per normalized company; refresh atomically replaces its payload.
- `company_intelligence_ttl_days` defaults to 30. Expiry changes presentation only; it does not trigger work.

## Slice 2 — Job API and background refresh

**Files:**

- Modify `src/resume_agent/api/schemas/jobs.py`
- Modify `src/resume_agent/api/routers/jobs.py`
- Add API tests

**Contract (refined 2026-08-29):**

- `GET /api/jobs/{job_id}` and `GET /api/jobs/{job_id}/company-intelligence` return the same state-discriminated resource: `unavailable` (missing company), `empty` (researchable but not researched), or `ready` (typed evidence). `canRefresh` and `isStale` are authoritative; legacy `capability` and `stale` fields remain as deprecated compatibility projections.
- `POST /api/jobs/{job_id}/company-intelligence/refreshes` is the canonical asynchronous refresh subresource. The original `POST /api/jobs/{job_id}/company-intelligence` remains an undocumented compatibility alias so already-shipped clients do not break.
- Refresh singleton identity is the normalized company, while run metadata keeps `jobId` for UI correlation.
- A sibling job at the same company sees the refreshed dossier on its next read.

## Slice 3 — Research tab

**Files:**

- Create `web/src/features/job/CompanyIntelligencePanel.tsx`
- Create `web/src/features/job/CompanyIntelligenceEvidence.tsx`
- Create `web/src/features/job/ResearchPanel.tsx`
- Add the mutation hook in `web/src/features/job/use-job-mutations.ts`
- Modify `web/src/components/JobModal.tsx`
- Modify run completion labels
- Add component/modal tests

**Experience:**

- Add a first-class `Research` tab beside Sponsorship.
- Use one shared header and notice geometry for Company Intelligence and Sponsorship so titles, icons, actions, status blocks, and mobile stacking align.
- Show a useful empty state, active/failure state, stale warning, retrieval date, research-axis cards, source list, and the evidence caveat.
- Links open in a new tab with safe `rel` attributes.
- Refresh is explicit, accessible, and disabled while the company-scoped run for this job is active.

## Slice 4 — Interview reuse

**Files:**

- Modify `src/resume_agent/interview/store.py`
- Modify `src/resume_agent/services/mock_interview.py`
- Modify `src/resume_agent/interview/agent.py`
- Add interview snapshot/rendering tests

**Contract:**

- Opening a new interview copies the current dossier into `InterviewContext.company_intelligence`.
- Existing session JSON without the field remains valid.
- Prompt rendering labels the block as untrusted company research and includes only the frozen payload.
- Refreshing company intelligence after a session opens does not alter that session.

## Verification

1. Focused Python tests for grounding, cache freshness, job API, and interview context.
2. Regenerate `contracts/openapi.json`, `contracts/ts/api.ts`, and `web/src/lib/api/schema.ts`.
3. Focused Vitest coverage for the panel, run states, and Research tab wiring.
4. Python lint/type checks and web lint/type checks.
5. Broad backend and frontend suites where runtime permits.
6. Review `git diff --check`, branch status, and the final diff for unrelated changes.
