# Agent Quality & Workflow — Eval Harness (Phase 0)

**Status:** approved (design), pending implementation plan
**Date:** 2026-06-29
**Branch:** `feat/agent-quality-evals`
**Scope:** Phase 0 of a four-phase effort to improve the quality and workflow of the
resume tailoring/generation agents. This spec details **Phase 0 only**; Phases 1–3 are
recorded as a roadmap and each gets its own spec → plan cycle later.

---

## 1. Background

The tailoring harness (`src/resume_agent/tailor/`) is a linear draft→validate→revise loop:

```
tailor (premium) ─→ ResumeContent w/ provenance ids
  └→ provenance gate (deterministic, code)        ← cheap gate first; skips panel on fail
       └→ panel (concurrent, 5 reviewers):
            fact-check (gate, premium) · ats-keyword (mid) · recruiter (mid)
            · hiring-manager (premium) · concision (mid)
            └→ aggregate (gates pass + weighted score ≥ 85)
                 └→ reviser (premium) ─→ loop up to max_rounds=3
```

The architecture is already strong: deterministic gate before the expensive panel; fact-lock
as a hard gate separate from scored quality; smallest-sufficient input per reviewer; concurrent
error-isolated panel; writer/reviser/reviewer kept as separate lanes; prompt-injection framing;
structured Pydantic outputs throughout. (`tailor/workflow.py`, `tailor/panel.py`,
`tailor/provenance.py`, `tailor/verdict.py`, `tailor/agents.py`, `config/review.yaml`.)

### The gap this phase closes

The entire quality apparatus — five reviewers, 0–100 self-calibrated scores, the `score_threshold:
85`, `max_rounds: 3` — is **unmeasured**. There is no ground-truth set proving the loop produces
good resumes, that scores improve across rounds, that fact-check actually catches fabrication, or
that any given reviewer pulls its weight. Per the agents-best-practices rule, you should not tune
or extend a multi-agent system before measurable evals exist. Phase 0 builds those evals; Phases
1–3 are then changes *measured against* this harness.

## 2. Goals / Non-goals

**Goals**
- A trustworthy way to answer "is a tailored resume good, and which agent is the weak link?"
- Keep CI deterministic and offline (the project's hard rule: tests run with no API key, no
  network, all agents faked).
- Produce a real, paid-on-demand quality + cost number when the user chooses to run it.

**Non-goals (this phase)**
- No changes to the tailoring loop, prompts, reviewers, or config. Phase 0 only *observes*.
- No automated judge-vs-human calibration (one-time human gate, documented).
- Cover-letter evals are deferred (the loop asymmetry is noted as a Phase 2+ follow-up).

## 3. Four-phase roadmap (context only; Phase 0 is this spec)

| Phase | Theme | Why this order |
| --- | --- | --- |
| **0** | **Evals (this spec)** | Foundation — the other three are unfalsifiable without it. |
| 1 | Loop reliability | Lowest risk; harness proves it immediately. keep-best-round, regression detection, early-exit on passed reviewers. |
| 2 | Output quality | Highest risk (can threaten fact-lock); match-plan step before drafting, rubric-anchored reviewers, sharper revise prompt. Guarded by Phase 1 + evals. |
| 3 | Cost / latency | Last, so we don't optimize a moving target. Cache-aware prompt ordering, skip-passed reviewers, tier escalation. |

## 4. Phase 0 design

### 4.1 Decisions (locked)

1. **Two-tier evals.** Offline invariant tier (in `pytest`, faked, CI) + live judged tier
   (separate, API-key-gated, opt-in, costs money).
2. **Hand-authored adversarial golden cases.** Each `(profile, JD)` pair is seeded with
   fabrication bait and ships hard assertions + a judge rubric.
3. **Judge measures output quality *and* reviewer efficacy** (the meta-eval), anchored once by a
   human.

### 4.2 Layout

The live tier lives **outside** `tests/` so `make test-py` (which collects `tests/`) never makes a
paid call; the offline tier lives **under** `tests/` so it runs in CI automatically.

```
evals/
  cases/case_01_*.json        # hand-authored adversarial cases (hermetic)
  profiles/*.json             # shared ProfileFacts, referenced by cases (dedupe)
  schema.py                   # EvalCase model + loader
  judge.py                    # build_judge_agent + JudgeVerdict (separate lane, premium)
  runner.py                   # run ONE case through the REAL loop, capture all rounds
  metrics.py                  # trap_recall · panel_agreement · convergence · cost
  report.py                   # markdown/console report + "weakest reviewer" callout
  run_eval.py                 # CLI entry: load cases -> run -> report (reads .env key)
  CALIBRATION.md              # one-time human-anchor record
tests/eval/test_eval_machinery.py   # OFFLINE: unit-tests metrics + trap-checker (faked, CI)
```

Build integration:
- New `make eval` target → `$(UV) run python -m evals.run_eval` (needs a real key; not part of
  `make test`/`make verify`).
- Add `evals` to `lint-py` scope (`ruff check src tests evals`).

### 4.3 Case schema (hermetic, adversarial)

```python
class Trap(BaseModel):
    kind: Literal["missing_skill", "adjacent_skill", "inflatable_metric", "seniority_inflation"]
    forbidden_terms: list[str]      # the final resume must NOT contain/claim these
    description: str

class EvalCase(BaseModel):
    id: str
    profile_ref: str                # -> evals/profiles/<name>.json (a ProfileFacts)
    jd_text: str
    criteria: JobCriteria | None    # None => extract live (--live-criteria); embedded => isolate loop
    traps: list[Trap]
    must_cite: list[str]            # provenance ids expected to appear in the output
    rubric: list[str]               # judge dimensions, e.g. ["relevance", "impact", "concision"]
```

Each profile in `evals/profiles/` is a real `ProfileFacts` instance so cases reuse `index_facts`
and the actual loop unchanged. Traps are profile↔JD *mismatches*: a required skill absent from the
profile, an adjacent-but-different skill, a metric tempting to inflate, a seniority the profile
doesn't support.

### 4.4 The two signals per run (the meta-eval)

**Deterministic (no model) — ground truth, never lies:**
- `trap_avoided` — final resume free of every trap's `forbidden_terms` (term + light normalization).
- `provenance_ok` — reuse `check_provenance`.
- `must_cite_covered` — every expected provenance id present in the output's `referenced_ids`.
- `budget_ok` — output honors `length_budget`.

**Judge (separate premium agent, profile-blind):** input = final resume + JD + rubric + the case's
traps. Output:

```python
class DimensionScore(BaseModel):
    dimension: str
    score: int          # 0-100
    rationale: str
class JudgeVerdict(BaseModel):
    output_quality: int          # 0-100 overall
    dimensions: list[DimensionScore]
    trap_violations: list[str]   # traps the judge believes were violated (cross-check)
    summary: str
```

Profile-blind on purpose: the judge grades **quality**, not fact-lock. Fact-lock is owned by the
deterministic checks and the in-loop fact-check reviewer; the judge re-deriving it would just add a
second unvalidated fact-checker.

**Reviewer efficacy (computed across cases) — this is what makes "improve the agents" actionable:**
- `trap_recall` — when a *draft in any round* contained a trap term, did the **fact-check**
  reviewer raise an issue against it? fact-check's true-positive rate on planted fabrication.
- `panel_agreement` — correlation of each reviewer's score with the judge's `output_quality`
  across cases. A reviewer whose score doesn't track quality is miscalibrated → names the Phase 2
  target.
- `convergence` — rounds-to-pass distribution, and whether the aggregate score **improved or
  regressed** per round. Direct evidence motivating Phase 1's keep-best-round.

`runner.py` captures **all** `TailorRound`s — `run_tailor_review` already returns the full list, so
per-round critiques are available for `trap_recall` and `convergence` with **no change to the
loop**. This existing legibility artifact is why Phase 0 is observation-only.

### 4.5 Judge anchoring (one-time human gate)

Run the live tier once; the user human-rates ~5 final resumes 0–100; compare to the judge's
`output_quality`. If mean absolute error < ~10, the judge is trusted and the result is recorded in
`evals/CALIBRATION.md` (cases rated, human scores, judge scores, MAE, judge model + prompt hash).
Re-run the anchor only when the judge prompt or model changes. Deliberately not automated: an
unvalidated judge is the disease this phase cures, so a human signs off once.

### 4.6 Offline tier scope (honest)

With faked agents there is no real quality to measure, so the CI tier tests the **harness's own
logic**, deterministically:
- the trap-checker flags a resume containing a forbidden term and passes a clean one;
- `metrics.py` computes `panel_agreement` / `convergence` / `trap_recall` correctly on scripted
  rounds and scores;
- the case loader validates / round-trips `EvalCase` JSON, and rejects malformed cases.

Richer loop-invariant tests (keep-best-round, idempotent revision) land **with Phase 1**, since
they assert behavior Phase 1 introduces.

### 4.7 CLI / run flow (`run_eval.py`)

Per case: build the **real** tailor bundle → (embed criteria, or `--live-criteria` to extract) →
`run_tailor_review(...)` capturing all rounds → deterministic checks → judge the final content →
accumulate. Then `report.py` renders a per-case table + aggregate + a "weakest reviewer" callout,
written to `evals/reports/<timestamp>.md` and echoed to console. Flags: `--cases <dir>`,
`--model <id>` (override tiers), `--live-criteria`, `--limit N`.

### 4.8 Resolved leanings

1. **Criteria source:** embed `JobCriteria` in each case by default (isolates the tailor/review
   loop, deterministic input); `--live-criteria` also exercises the extract agent.
2. **Cost capture:** read real token usage off the agno `RunOutput` if it exposes
   `usage`/`metrics`; **fall back to a call-count × tier proxy**. (Implementation must verify what
   agno 2.6.x surfaces; usage is not captured in the loop today.)
3. **Seed size:** 8 cases (~2 per trap kind) to keep authoring honest and the first paid run cheap,
   then grow.

## 5. Testing

- **Offline (CI, `make test-py`):** `tests/eval/test_eval_machinery.py` — trap-checker, metrics, and
  case-loader unit tests with scripted/faked inputs. No model, no network.
- **Live (opt-in, `make eval`):** the real harness; not part of CI. Its "test" is the human anchor
  in `CALIBRATION.md` plus the generated report.

## 6. Success criteria

- `make eval` runs all seed cases through the real loop and emits a report with: per-case
  `output_quality`, deterministic pass/fail, `trap_recall`, `panel_agreement` per reviewer,
  convergence (rounds + improved/regressed), and cost.
- The report **names the weakest reviewer** (lowest `panel_agreement` and/or `trap_recall`).
- `make test-py` stays fully offline and green, with new machinery tests included.
- `CALIBRATION.md` records a judge anchored to within ~10 MAE of human ratings.
- Zero changes to `src/resume_agent/tailor/` behavior (observation-only phase).

## 7. Open items for the implementation plan

- Confirm agno `RunOutput` usage fields (item 4.8.2).
- Decide normalization for trap term matching (case-fold + word-boundary; avoid matching "Java" in
  "JavaScript").
- Whether `panel_agreement` needs ≥ N cases to be meaningful (report it as "insufficient data"
  below a threshold rather than a misleading correlation).
```
