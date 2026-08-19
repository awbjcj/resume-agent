# UCCM Phase 5 Shadow Match Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development and superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compute reproducible, typed per-requirement Match v2 results beside the actual legacy matcher without changing ranking, suggestions, or tailoring in shadow mode.

**Architecture:** Match one typed requirement against evidence-backed assertions and verified requirement-lane facts. Apply hard gates before bounded graph retrieval, calculate a transparent feature vector, then classify through versioned deterministic policy. Store both actual legacy coverage and precise v2 status. Build an offline evaluator whose signed report controls later UCCM activation.

**Tech Stack:** Pure Python matching core, Pydantic result models, pytest parametrization, JSONL gold fixtures, deterministic evaluation reports.

**Spec:** `docs/superpowers/specs/2026-08-19-universal-career-capability-matrix-profile-match-gap-design.md`

## Global Constraints

- Exact statuses: `verified_exact`, `verified_equivalent`, `covered_broader`, `covered_narrower`, `transferable`, `partial`, `level_gap`, `context_gap`, `recency_gap`, `evidence_gap`, `tool_gap`, `credential_gap`, `unknown`, `absent`.
- Hard gates execute first and no graph path can bypass them.
- Traversal uses approved, active, scope-visible edges; an allowlist, direction rules, confidence floor, and maximum path length.
- Same category/domain, embeddings, lexical resemblance, and co-occurrence may retrieve candidates but cannot establish coverage.
- Transfer is directional, conditional, evidence-supported, non-claiming, and does not satisfy strict requirements.
- `legacy_coverage` is produced by the existing matcher, never mapped backward from v2.
- Every result stores revisions, feature values, path, evidence IDs, policy outcomes, and concise explanations, never hidden reasoning.

## File Structure

| File | Responsibility |
| --- | --- |
| `src/resume_agent/matching/models.py` | Feature vector, graph path, policy outcome, v2 result, shadow pair. |
| `src/resume_agent/matching/traversal.py` | Bounded policy-approved candidate retrieval. |
| `src/resume_agent/matching/policy.py` | Hard gates and status classification. |
| `src/resume_agent/matching/engine.py` | Per-requirement orchestration and deterministic batch result. |
| `src/resume_agent/evals/uccm.py` | Gold loader, metrics, ablations, release-gate report. |
| `evals/fixtures/uccm_match_gold.jsonl` | Curated stratified offline cases; no fabricated labels. |
| `tests/test_uccm_matching_*.py` | Traversal, gates, features, statuses, determinism. |
| `tests/test_uccm_eval.py` | Metric and gate calculations. |

### Task 1: Define status acceptance table

- [ ] Add a strict-xfail parametrized test with one minimal fixture for every precise status and separate actual legacy coverage.
- [ ] Add adversarial same-domain, lexical-similar, embedding-similar, and co-occurrence negatives.
- [ ] Run baseline and commit.

### Task 2: Add match models and bounded traversal

- [ ] Write failing tests for path direction, allowed predicates, maximum depth, cycles, inactive edges, scope, confidence, and stable ordering.
- [ ] Implement immutable path/result models and `MATCHING_POLICY_REVISION = "uccm-match-v1"`.
- [ ] Implement bounded traversal with explicit predicate/direction policy; return candidate paths only, not a coverage decision.
- [ ] Run tests, simplify traversal state representation, and commit.

### Task 3: Implement hard gates and feature vector

- [ ] Write failing tests for credentials/licenses, jurisdiction, work authorization, clearance, strict product/standard, and explicit non-substitution.
- [ ] Implement gate outcomes before graph retrieval.
- [ ] Write failing tests for identity/equivalence/path direction/task/knowledge/subskill/tool-family/context/audience/scale/proficiency/autonomy/complexity/recency/evidence/importance/strictness features.
- [ ] Implement state-based feature calculation using only stored assertions, requirement facts, and approved graph edges.
- [ ] Run tests and commit.

### Task 4: Classify every precise status

- [ ] Write failing precedence tests so exact/equivalent/strict gaps outrank soft partial/transfer; unknown evidence differs from proven absence.
- [ ] Implement deterministic policy returning status, confidence, concise reason codes, recommended action, source requirement, candidate assertion, evidence refs, and path.
- [ ] Prove transferable/partial results retain the candidate concept label and cannot emit the target label as a claim.
- [ ] Prove repeated runs and reordered equivalent inputs serialize identically apart from excluded runtime metadata.
- [ ] Run tests and commit.

### Task 5: Compute shadow pairs without changing legacy behavior

- [ ] Write a failing seam test that invokes the current legacy matcher and v2 on the same snapshot and asserts byte-compatible legacy output/ranking.
- [ ] Add a shadow service returning `{legacy_coverage, v2_result}`; in `legacy` mode skip v2, in `shadow` record v2, and in guarded `uccm` expose v2 primary while retaining legacy.
- [ ] Record counts, unresolved/fallback reasons, and latency through the existing observability seam without graph mutation.
- [ ] Run legacy matcher and shadow tests; commit.

### Task 6: Build evaluation and release gates

- [ ] Write failing evaluator tests using tiny synthetic fixtures for exact precision, strict false-positive rate, claim precision, transfer precision, adversarial false transfer, type macro-F1, status macro-F1/minimum, correction propagation, and deterministic reproduction.
- [ ] Implement metric math and exact thresholds from the spec. A missing metric, insufficient denominator, unsigned/unreviewed gold set, or failed threshold yields `eligible=false`.
- [ ] Add JSONL schema and a reviewed-fixture manifest field. Do not claim the full 12-family gate passes without reviewed labels.
- [ ] Implement ablation flags and reports for current adjacency, exact-only, hierarchy, task/knowledge, approved transfer, proficiency/context, retrieval type, classifier type, and overlays.
- [ ] Remove strict xfail; run all matching/eval tests, Ruff, targeted Pyright, and commit Phase 5 with a migration/rollback note.

