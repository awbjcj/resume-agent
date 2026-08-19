# UCCM Remaining Program Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the compatibility-first UCCM program after the typed graph adapter by implementing term typing, evidence-backed profile assertions, typed job requirements, shadow Match Engine v2, layered API/UI projections, and a release-gated production switch.

**Architecture:** Extend the immutable effective capability snapshot already introduced in Phases 0–1. Persist separately versioned profile, extraction, and matching artifacts; derive every legacy projection from the same canonical artifacts; keep `CAREER_CAPABILITY_MODE=legacy|shadow|uccm` as the sole deployment selector. `shadow` records v2 without changing decisions, and `uccm` is allowed only when a stored offline evaluation report satisfies every release gate.

**Tech Stack:** Python 3.13, Pydantic v2, SQLModel JSON compatibility fields, FastAPI/OpenAPI, React 19, TypeScript, Vitest/Testing Library, pytest, Ruff, Pyright.

**Spec:** `docs/superpowers/specs/2026-08-19-universal-career-capability-matrix-profile-match-gap-design.md`

## Global Constraints

- Use strict RED -> GREEN -> REFACTOR for every behavioral change. Record the failing test before production edits.
- Work on the current feature branch and preserve unrelated edits in `src/resume_agent/db.py`, `src/resume_agent/tracking/migrate.py`, and `tests/test_migrate.py`.
- Execute phases in this order: 2, 3, 4, 5, 7, 8. Phase 6 bulk external imports are out of scope under the governing spec.
- Preserve stored profiles, jobs, matrices, resumes, legacy routes, legacy enum values, and legacy match behavior.
- Never use category, learned-domain, lexical, embedding, or co-occurrence similarity alone as semantic coverage.
- Never infer credentials, work authorization, legal eligibility, protected traits, or physical capability from ordinary text.
- Never relabel candidate evidence with a target requirement for `transferable` or `partial` results.
- Version term-typing, assertion, extraction, and matching policies independently.
- Provider/schema failure produces an observable `unknown` result and never mutates the approved graph.
- Regenerate OpenAPI and TypeScript contracts for every additive API change.
- Use no network or provider credentials for the deterministic verification gates.

## Phase Plans

1. `2026-08-19-uccm-phase2-term-typing.md`
2. `2026-08-19-uccm-phase3-profile-assertions.md`
3. `2026-08-19-uccm-phase4-typed-job-requirements.md`
4. `2026-08-19-uccm-phase5-shadow-match-engine.md`
5. `2026-08-19-uccm-phase7-projections-tailoring.md`
6. `2026-08-19-uccm-phase8-controlled-switch.md`

## Program Acceptance

- [ ] Run each phase plan in order and commit only that phase's files after its focused gate passes.
- [ ] Compare `git diff main...HEAD` and `git log main..HEAD` for the final review.
- [ ] Perform the Standards review and Spec review sequentially inline; fix all critical/high findings and all safe medium findings.
- [ ] Apply code-simplification only to changed code, with behavior-preserving tests after every refactor batch.
- [ ] Run backend pytest, Ruff, targeted/full Pyright as configured, frontend Vitest, ESLint, build, OpenAPI drift, and contract-generation gates.
- [ ] Verify profile build -> stored assertions -> typed job requirements -> shadow/v2 match -> match-gap API -> tailoring compatibility in one cross-seam test.
- [ ] Document any release gate that remains honestly unproven; the guarded UCCM selector must reject activation rather than inventing success.
