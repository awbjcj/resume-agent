# UCCM Phase 8 Controlled Switch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development, superpowers:code-review, superpowers:code-simplification, and superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow a reversible UCCM-primary experience only when a reviewed evaluation report proves all release gates, retain shadow/legacy rollback, and finish with an inline whole-branch review and simplification.

**Architecture:** Resolve the existing single deployment mode through a pure activation policy. `uccm` requires a complete, reviewed, revision-matching evaluation report; otherwise it falls back to `shadow` with a stable reason. No legacy field or stored artifact is deleted in this phase.

**Tech Stack:** Existing settings and snapshot modes, deterministic evaluation reports, pytest, frontend mode tests, Git diff review.

**Spec:** `docs/superpowers/specs/2026-08-19-universal-career-capability-matrix-profile-match-gap-design.md`

## Global Constraints

- Do not create extra feature booleans. Use only `CAREER_CAPABILITY_MODE=legacy|shadow|uccm`.
- A missing, stale, unreviewed, unsigned, incomplete, or failing report cannot activate primary UCCM behavior.
- Fallback is observable and retains v2 shadow computation when safe.
- Historical profiles/jobs/resumes remain readable; no backfill pretends unknown revisions were known.
- Deprecation means documented compatibility window, not deletion in this program.

## File Structure

| File | Responsibility |
| --- | --- |
| `src/resume_agent/matching/activation.py` | Pure release-gate decision and stable fallback codes. |
| `src/resume_agent/profile/effective.py` | Resolve requested mode through activation policy. |
| `src/resume_agent/services/match_gap.py` | Choose primary presentation while retaining legacy data. |
| `src/resume_agent/services/tailoring.py` | Enforce gated primary semantics and rollback. |
| `tests/test_uccm_activation.py` | Complete gate, stale report, rollback, and compatibility tests. |
| `docs/notes/2026-08-19-uccm-controlled-switch.md` | Operator procedure, observability, rollback, deprecation window. |

### Task 1: Implement fail-closed activation

- [ ] Write failing tests for every release threshold, missing denominator, unreviewed report, revision mismatch, stale report, tampered checksum, and passing report.
- [ ] Implement a pure decision returning requested/effective mode, eligibility, stable reason code, report revision, taxonomy revision, assertion/extraction/matching policies, and checked thresholds.
- [ ] Wire mode resolution so requested `uccm` falls back to `shadow`; requested `legacy` and `shadow` do not require a report.
- [ ] Run focused tests and commit.

### Task 2: Verify production/rollback behavior

- [ ] Write failing tests proving eligible `uccm` makes v2 primary without dropping actual legacy coverage and that rollback changes decisions without rewriting artifacts.
- [ ] Add observability for build latency, assertion/unknown/status/correction/fallback/stale/provider metrics using concise structured fields.
- [ ] Verify invalid provider output leaves graph/corrections untouched and results unknown/failed.
- [ ] Run backend and frontend mode tests; commit.

### Task 3: Inline whole-branch Standards review against `main`

- [ ] Capture `git log --oneline main..HEAD` and `git diff --stat main...HEAD`.
- [ ] Read applicable root/nested `CLAUDE.md` files and review changed code for repository standards plus the smell baseline.
- [ ] Record findings by severity with file/line evidence; fix critical/high and safe medium findings using reproduction tests first.
- [ ] Rerun affected tests and commit review fixes separately.

### Task 4: Inline whole-branch Spec review against `main`

- [ ] Map every spec implementation/testing/out-of-scope statement to code and evidence.
- [ ] Verify Phase 6 imports are absent, external-source seams remain, legacy behavior remains, and activation cannot bypass gates.
- [ ] Record missing/partial/extra findings separately from Standards; fix in-scope gaps with RED -> GREEN -> REFACTOR.
- [ ] Rerun affected tests and commit spec fixes separately.

### Task 5: Simplify changed code without behavior drift

- [ ] Inspect blame/context for complex changed functions and identify duplication, message chains, repeated switches, speculative abstractions, and primitive/data clumps.
- [ ] Make small behavior-preserving refactors only in `main...HEAD` changed code; run focused tests after each batch.
- [ ] Commit simplification separately and verify the final diff contains no placeholders, debug code, or dead compatibility branches.

### Task 6: Final verification and handoff

- [ ] Run full backend pytest, Ruff, repository Pyright gate, OpenAPI drift/generation, frontend Vitest, ESLint, and production build.
- [ ] Run the cross-seam profile-building/gap-matching/tailoring test in each effective mode and old-artifact compatibility fixtures.
- [ ] Document exact passing evidence and any honest external/reviewed-gold limitation. Never label UCCM production-ready if the reviewed gold gate is unavailable.
- [ ] Use superpowers:finishing-a-development-branch and present the branch completion options without auto-merging or pushing.

