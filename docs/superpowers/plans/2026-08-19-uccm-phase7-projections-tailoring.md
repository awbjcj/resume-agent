# UCCM Phase 7 Projections and Tailoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development and superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose accessible UCCM profile and match-gap projections and make tailoring consume the same pinned snapshot, assertions, requirements, and matches while preserving legacy adapters.

**Architecture:** Add one application service that validates snapshot/artifact coherence and assembles legacy demand plus typed requirements/results and layered rollups. API schemas are additive. The frontend renders backend-provided semantics and source drilldowns; it may recompute filter-local demand counts but never match status. Tailoring receives a pinned UCCM context and derives the old `SkillMatchContext` from it.

**Tech Stack:** FastAPI/Pydantic, React 19/TypeScript, generated OpenAPI contracts, Vitest/Testing Library, existing tailoring services.

**Spec:** `docs/superpowers/specs/2026-08-19-universal-career-capability-matrix-profile-match-gap-design.md`

## Global Constraints

- One response uses one effective snapshot and one matching profile artifact. On mismatch, rebuild through the shared seam or return explicit `stale`/`unavailable`.
- Preserve jobs, skills, domains, categories, edges, filters, maintenance state, and legacy coverage fields.
- Requirements/context remain a separate lane from candidate capabilities.
- UI groups may simplify statuses to Covered/Transferable/Partial/Gap/Unknown, but precise status and provenance remain drillable.
- Tailoring fact-lock, numeric evidence, skill naming, and existing gates are unchanged.
- Transferable/partial can guide emphasis/questions but never produce the target term as a candidate claim.

## File Structure

| File | Responsibility |
| --- | --- |
| `src/resume_agent/services/match_gap.py` | Coherent application assembly and stale handling. |
| `src/resume_agent/api/schemas/match_gap.py` | Additive typed requirement/result/rollup/drilldown fields. |
| `src/resume_agent/api/routers/match_gap.py` | Thin router over service. |
| `src/resume_agent/tailor/context.py` | Pinned UCCM context and deterministic legacy adapter. |
| `src/resume_agent/services/tailoring.py` | Load/persist pinned revisions and context. |
| `src/resume_agent/tailor/service.py` | Consume context without weakening gates. |
| `web/src/features/match-gap/*` | Layered projections, separate requirement lane, source drilldown, stale state. |
| `tests/api/test_match_gap.py`, `tests/test_tailoring_service.py` | Cross-path revision and compatibility tests. |
| `web/src/features/match-gap/*.test.tsx` | Accessibility, responsive, status, and drilldown tests. |

### Task 1: Establish one cross-path acceptance seam

- [ ] Add a strict-xfail test that builds profile assertions and typed job requirements, computes shadow results, requests match-gap, builds legacy tailoring context, and persists a resume attempt.
- [ ] Assert the same taxonomy/facts/assertion/extraction/matching revisions and assertion IDs across all artifacts.
- [ ] Add mismatched-revision fixtures asserting rebuild or explicit stale response, never blended data.
- [ ] Run baseline and commit.

### Task 2: Assemble additive match-gap response

- [ ] Write failing service tests for typed requirements, precise results, actual legacy coverage, UCCM layers/types, explanations, raw demand edges, and rollups.
- [ ] Move business assembly out of the router into `services/match_gap.py` and keep legacy serializer fields byte-compatible.
- [ ] Aggregate demand from typed requirements while retaining exact source, kind, strictness, job ID, and requirement ID.
- [ ] Add drilldown records linking rollups to jobs, source text, assertions/verified facts, evidence, status, confidence, and action.
- [ ] Run service/API tests and commit.

### Task 3: Regenerate contracts and implement UI projections

- [ ] Write failing schema/contract tests proving new fields are additive and closed enums match TypeScript.
- [ ] Regenerate OpenAPI and TypeScript contracts.
- [ ] Write failing frontend tests for six layers, separate requirement lane, precise/simplified labels, unknown versus absent, legacy-adjacent versus v2 transfer, source/evidence drilldown, stale/unavailable states, keyboard use, non-color cues, small screens, and reduced motion.
- [ ] Implement backend-driven rendering; do not reconstruct paths or semantic statuses in the browser.
- [ ] Run targeted Vitest, ESLint for changed files, and production build; commit.

### Task 4: Pin tailoring to the same context

- [ ] Write failing tests that direct exact/approved broader-narrower matches may select only claimable evidence, while transferable/partial only influence emphasis/questions and retain the candidate name.
- [ ] Add `UccmTailoringContext` with all revisions, typed requirements, result IDs/statuses, assertion IDs, and legacy projection.
- [ ] Derive current `SkillMatchContext` deterministically from the same context; do not run a second matcher.
- [ ] Persist the complete context in an additive resume-version JSON field or existing extensible artifact without rewriting history; old versions load with defaults.
- [ ] Run fact-lock, skill-name, numeric-evidence, tailoring-service, and resume-version tests; commit.

### Task 5: Phase gate

- [ ] Remove strict xfail and run the cross-path test plus match-gap, API, tailoring, OpenAPI, TypeScript, and frontend suites.
- [ ] Verify rollback to `shadow` and `legacy` keeps all old artifacts readable and legacy displays unchanged.
- [ ] Add migration/rollback note and commit Phase 7.

