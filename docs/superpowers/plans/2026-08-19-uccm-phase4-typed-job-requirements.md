# UCCM Phase 4 Typed Job Requirements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development and superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist source-grounded typed requirements for new and legacy jobs while retaining current must-have, nice-to-have, and technology lists.

**Architecture:** Run a deterministic requirement binder after the existing lean LLM `JobCriteriaExtract` step. It uses Phase 2 term typing, exact spans when the full JD is available, and a legacy adapter when only criteria lists exist. Typed records are canonical; legacy lists are deterministic projections with explicit reconciliation issues.

**Tech Stack:** Pydantic v2, existing discovery extraction pipeline, SQLModel JSON job criteria, pytest.

**Spec:** `docs/superpowers/specs/2026-08-19-universal-career-capability-matrix-profile-match-gap-design.md`

## Global Constraints

- Keep `JobCriteriaExtract` lean enough for existing provider schema limits.
- Preserve source text and exact `[start,end)` offsets for new extraction; legacy rows use `legacy_list_item` provenance and nullable offsets.
- Requirement kinds and strictness values are closed, typed vocabularies.
- Credentials, licenses, authorization, clearance, jurisdiction, and explicit non-substitutable products never receive semantic transfer.
- Ambiguous phrases remain `unknown` and still retain provenance.
- Existing criteria JSON and clients remain readable; inconsistencies are surfaced.

## File Structure

| File | Responsibility |
| --- | --- |
| `src/resume_agent/models/requirements.py` | Typed requirement, source span, provenance, revision, reconciliation models. |
| `src/resume_agent/discovery/requirements.py` | Deterministic binder, span locator, legacy adapter, legacy projection. |
| `src/resume_agent/models/job.py` | Additive typed requirement/revision/reconciliation fields. |
| `src/resume_agent/discovery/pipeline.py` | Bind requirements after existing extraction and before JSON persistence. |
| `tests/test_job_requirements.py` | Kinds, strictness, spans, ambiguity, stable IDs. |
| `tests/test_discovery_pipeline.py` | Persistence and provider-failure compatibility. |

### Task 1: Establish source-span acceptance

- [ ] Add a strict-xfail test with one JD containing a credential, explicit tool, years of experience, work authorization, location/schedule, responsibility, and preferred capability.
- [ ] Assert exact slices equal stored source text, requirement IDs are stable, and legacy projections match current lists.
- [ ] Add a legacy-only criteria fixture and assert `legacy_list_item` provenance with unknown offsets.
- [ ] Run baseline and commit.

### Task 2: Add requirement models and policy

- [ ] Write failing tests for all requirement kinds and strictness values, minimum proficiency, context, importance, evidence expectation, recency, confidence, taxonomy revision, extraction policy, and term decision ID.
- [ ] Implement `JOB_EXTRACTION_POLICY_REVISION = "job-requirements-v1"` and stable IDs over job/source identity, exact source span or legacy item identity, parsed concept, and policy revision.
- [ ] Validate source offsets and strict lane/type combinations; reject a credential represented as an ordinary skill requirement.
- [ ] Run tests and commit.

### Task 3: Implement deterministic binding and legacy adaptation

- [ ] Write failing tests for rule-first binding, duplicated phrases, repeated substrings, ambiguous phrases, and strictness assignment.
- [ ] Implement ordered deterministic lane rules and use Phase 2 assistance only for unresolved semantic phrases.
- [ ] Implement the legacy adapter over `must_have_skills`, `nice_to_have_skills`, `tech_stack`, and existing requirement lanes.
- [ ] Implement deterministic legacy projection and structured reconciliation issues; never silently prefer mismatched data.
- [ ] Run focused tests and commit.

### Task 4: Integrate discovery persistence

- [ ] Write a failing discovery-pipeline test showing extraction persists typed requirements, policy/taxonomy revisions, and unchanged legacy lists in `criteria_json`.
- [ ] Add fields to `JobCriteria` only, not the lean extraction response, then bind after extraction using the job ID and JD text.
- [ ] On term/provider failure, persist an unknown requirement and observable failure reason; do not drop the original criterion.
- [ ] Verify old job JSON validates and no database migration is required because `criteria_json` is already JSON.
- [ ] Run discovery/model tests and commit.

### Task 5: Phase gate

- [ ] Remove strict xfail and add correction/revision sensitivity tests.
- [ ] Test must/preferred, product family, capability, credential, experience, authorization, location, schedule, physical/environmental, and unknown cases.
- [ ] Run focused tests, OpenAPI drift if schemas changed, Ruff, and targeted Pyright.
- [ ] Add migration/rollback note and commit Phase 4.

