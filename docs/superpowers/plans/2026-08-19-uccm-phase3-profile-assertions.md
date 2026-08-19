# UCCM Phase 3 Profile Assertions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development and superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make evidence-backed capability assertions the canonical profile representation while deriving byte-compatible legacy matrix rows.

**Architecture:** Build immutable assertions from `ProfileFacts`, typed terms, and one `EffectiveTaxonomy`. Assertions carry evidence, claimability, optional behavioral level, independent work dimensions, recency, use, and all dependent revisions. `SkillMatrix.rows` becomes a compatibility projection generated from assertions in the same atomic artifact.

**Tech Stack:** Pydantic v2, existing profile corpus/facts/matrix seams, atomic JSON, pytest.

**Spec:** `docs/superpowers/specs/2026-08-19-universal-career-capability-matrix-profile-match-gap-design.md`

## Global Constraints

- No assertion may cite a missing fact ID.
- Taxonomy membership, job title, learned domain, or model suggestion alone cannot create a claimable assertion or favorable level.
- Proficiency uses five behaviorally anchored levels; autonomy, complexity, responsibility scope, influence scope, and evidence confidence are independent and optional.
- `unknown` stays unknown. Legacy strength/recency are projections, not canonical proficiency.
- Rebuild is atomic and bound to facts, complete taxonomy snapshot, term-typing policy, and assertion-policy revisions.
- Existing matrix readers and old artifacts remain readable.

## File Structure

| File | Responsibility |
| --- | --- |
| `src/resume_agent/profile/assertions.py` | Assertion models, evidence validation, level dimensions, claimability, stable IDs. |
| `src/resume_agent/profile/assertion_builder.py` | Pure facts-to-assertions builder. |
| `src/resume_agent/profile/matrix.py` | Persist assertions/revisions and derive legacy rows from them. |
| `src/resume_agent/services/profile_build.py` | One atomic build seam for facts, assertions, and rows. |
| `src/resume_agent/api/schemas/profile.py` | Additive UCCM profile view contracts. |
| `tests/test_profile_assertions.py` | Assertion invariants and deterministic builds. |
| `tests/test_profile_matrix.py` | Legacy projection compatibility and old-artifact loading. |
| `tests/test_profile_build_service.py` | Atomic rebuild and revision sensitivity. |

### Task 1: Establish cross-seam acceptance

- [ ] Add a strict-xfail test that builds facts containing literal, inferred, self-reported, stale, disputed, and missing-evidence examples; builds the profile; and asserts assertions and legacy rows share evidence and revisions.
- [ ] Capture the current legacy row payload before implementation and assert the projection remains equal for the compatibility fixture.
- [ ] Run focused baseline and commit the acceptance test.

### Task 2: Add assertion domain models

- [ ] Write failing tests for statuses `evidenced`, `inferred`, `self_reported`, `assessed`, `disputed`, `unknown`; claimability states from the design authority; five named levels; and optional independent dimensions.
- [ ] Implement stable assertion IDs over concept, subject/profile, evidence IDs, assertion policy, facts revision, and taxonomy effective hash.
- [ ] Validate duplicate/missing evidence, illegal claimability/status combinations, and title-only dimension assignment.
- [ ] Run unit tests, refactor validation helpers, and commit.

### Task 3: Build assertions from facts

- [ ] Write failing state-based tests for literal skill facts, evidence-backed inferred skills, bullet/technology evidence, self-report without evidence, stale evidence, and ambiguity.
- [ ] Implement a pure builder that reuses the current evidence discovery logic, emits unknown dimensions when insufficient, and computes recency/usage separately from level.
- [ ] Preserve the candidate's literal display name and canonical concept ID; do not invent a target label.
- [ ] Run focused tests and commit.

### Task 4: Derive legacy rows and persist one atomic artifact

- [ ] Write failing tests proving every legacy row is derived from assertions and old matrix JSON without new fields still loads.
- [ ] Extend `SkillMatrix` with `assertion_policy_revision`, `term_typing_policy_revision`, and `assertions` using additive defaults.
- [ ] Refactor `build_matrix` into assertion build plus deterministic row projection; keep sort, aliases, category/group, strength, recency, and evidence behavior compatible.
- [ ] Update `load_matrix` freshness checks and `run_corpus_build` atomic save ordering.
- [ ] Run matrix/profile-build tests and commit.

### Task 5: Add layered profile projections and phase gate

- [ ] Write failing tests for core, transferable-function, domain/role, enabler, evidence-quality, and development-needs rollups; every rollup links to assertion/evidence IDs.
- [ ] Implement projection builders as read-only functions over assertions plus graph paths; never encode projection membership back into the graph.
- [ ] Add additive schema fields and regenerate contracts if the profile API exposes them in this phase.
- [ ] Remove strict xfail; run profile/assertion/matrix/service tests, old-artifact fixtures, Ruff, and targeted Pyright.
- [ ] Add migration/rollback note and commit Phase 3.

