# UCCM Phase 2 Term Typing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development and superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Type existing profile and job phrases without losing their original text or forcing ambiguous terms into `skill`.

**Architecture:** Add a pure deterministic classifier over the Phase 1 graph vocabulary, followed by an optional injected model-assisted classifier for unresolved phrases. Validate model output against the closed `ConceptType` vocabulary and emit `unknown` on ambiguity or failure. Store correction events separately from global graph identity and apply them through the effective snapshot seam.

**Tech Stack:** Pydantic v2, deterministic regex/rule tables, existing model factory/schema adapter for optional assistance, pytest, FastAPI/OpenAPI.

**Spec:** `docs/superpowers/specs/2026-08-19-universal-career-capability-matrix-profile-match-gap-design.md`

## Global Constraints

- Do not mutate `ConceptNode.type` in the approved global graph during a read.
- Preserve `original_text`, `normalized_text`, optional exact character offsets, source kind, source identifier, policy revision, confidence, decision source, and reason code.
- Deterministic lanes cover obvious credential, degree, duration, location, schedule, authorization, clearance, language, tool/product, method/standard, work context, and occupation phrases.
- Ambiguity is a first-class `unknown`, not `skill`.
- Model assistance is injected, schema-validated, optional, and cannot introduce a type outside `ConceptType` plus `unknown`.
- Corrections are auditable and scope-aware; a profile/tenant correction does not silently become global.

## File Structure

| File | Responsibility |
| --- | --- |
| `src/resume_agent/taxonomy/term_typing.py` | Typed phrase models, deterministic rules, optional model seam, validation, stable IDs. |
| `src/resume_agent/taxonomy/term_corrections.py` | Scoped correction records, deterministic replay, atomic JSON store. |
| `src/resume_agent/services/term_typing.py` | Batch service, correction commands, metrics summary. |
| `src/resume_agent/api/schemas/taxonomy.py` | Additive type-decision/correction request and response models. |
| `src/resume_agent/api/routers/taxonomy.py` | Thin endpoints over the service. |
| `tests/test_term_typing.py` | Rule, ambiguity, failure, span, and determinism tests. |
| `tests/test_term_corrections.py` | Scope, replay, audit, and atomic-write tests. |
| `tests/api/test_taxonomy_term_typing.py` | API and authorization boundary tests. |

### Task 1: Define the executable type-decision boundary

- [ ] Add a strict-xfail acceptance test that imports future symbols inside the test and asserts `AWS Certified Solutions Architect` -> `credential`, `Python` -> `tool_technology`, `five years` -> `requirement`, `remote` -> `work_context`, and `leadership` -> `unknown` when no governed concept disambiguates it.
- [ ] Assert source text and `[start, end)` offsets round-trip exactly and IDs are stable across reordered batches.
- [ ] Run `pytest tests/test_term_typing.py -v`; verify one strict xfail and no collection error.
- [ ] Commit the acceptance boundary.

### Task 2: Add closed models and deterministic rules

- [ ] Write failing unit tests for `TermTypingDecision`, `TermSource`, decision sources (`rule`, `model`, `correction`, `unknown`), and reason codes.
- [ ] Implement `TERM_TYPING_POLICY_REVISION = "term-typing-v1"` and stable SHA-256 IDs over source identity, source span, original text, and policy revision.
- [ ] Implement ordered rules with strict precedence: legal/credential -> degree/experience -> location/schedule/authorization/clearance -> language -> standard/method -> obvious product/tool -> explicit work activity/task -> unknown.
- [ ] Validate offsets against source text; reject mismatched spans instead of repairing them silently.
- [ ] Run focused tests, refactor duplicated result construction into one private helper, rerun once after the refactor, and commit.

### Task 3: Add optional model-assisted ambiguity resolution

- [ ] Write failing tests using a fake classifier: valid result is accepted; invalid type, low confidence, provider error, and altered source text become `unknown` with stable observable reason codes.
- [ ] Define a small injected `TermTypeAssistant` protocol; production adapter must use `build_model` and `expect_schema`, never provider imports.
- [ ] Ensure rule decisions never call the assistant and assistant output cannot override an explicit correction.
- [ ] Run focused tests and the prompt-contract tests; commit.

### Task 4: Add scoped correction replay

- [ ] Write failing tests for append-only correction events containing actor, scope, action, subject, prior/new type, rationale, evidence references, target revision, and timestamp.
- [ ] Implement atomic JSON persistence and deterministic effective selection by scope and event order; reject stale target revisions unless explicitly marked as a proposal.
- [ ] Add service methods to list decisions, correct one decision, and recompute a batch without mutating the approved graph.
- [ ] Run focused tests and commit.

### Task 5: Add thin API and phase gate

- [ ] Write failing API tests for read/list and correction endpoints, including tenant/profile isolation and invalid enum handling.
- [ ] Add schemas/router methods that delegate to the service and retain additive compatibility.
- [ ] Regenerate OpenAPI/TypeScript contracts; run drift tests.
- [ ] Remove strict xfail and run `pytest tests/test_term_typing.py tests/test_term_corrections.py tests/api/test_taxonomy_term_typing.py tests/test_agent_prompt_contracts.py -v` plus Ruff on changed files.
- [ ] Add a migration/rollback note and commit Phase 2.
