# Agent Quality & Workflow — Eval Harness (Phase 0)

**Status:** reviewed; implementation plan aligned
**Date:** 2026-06-29
**Branch:** `feat/agent-quality-evals`
**Scope:** Phase 0 of a four-phase effort to improve the quality and workflow of the
resume tailoring/generation agents. This spec details **Phase 0 only**; Phases 1–3 are
recorded as a roadmap and each gets its own spec → plan cycle later.

---

## 1. Background

The tailoring harness (`src/resume_tailor_harness/tailor/`) is a linear draft→validate→revise loop:

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
- An auditable baseline for "is a tailored resume good, and which agent is the likely weak link?"
- Keep CI deterministic and offline (the project's hard rule: tests run with no API key, no
  network, all agents faked).
- Produce paid-on-demand quality, token usage, and provider-reported cost when available.

**Non-goals (this phase)**
- No changes to the tailoring loop, prompts, reviewers, or config. Phase 0 only *observes*.
- No automated judge-vs-human calibration (one-time human gate, documented).
- Cover-letter evals are deferred (the loop asymmetry is noted as a Phase 2+ follow-up).
- Statistical significance from eight stochastic cases. Phase 0 is directional: confirm a weak
  reviewer across repeated live runs before changing production behavior.

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
  runner.py                   # run one real case + isolated fact-check probes
  metrics.py                  # trap_recall · panel_agreement · convergence
  usage.py                    # non-invasive RunOutput.metrics collection
  report.py                   # markdown/console report + "weakest reviewer" callout
  run_eval.py                 # CLI entry: load cases -> run -> report (reads .env key)
  reports/<timestamp>.json    # machine-readable rounds, resumes, critiques, usage, failures
  CALIBRATION.md              # one-time human-anchor record
tests/eval/test_*.py                # OFFLINE: focused machinery/orchestration tests (faked, CI)
```

Build integration:
- New `make eval` target → `$(UV) run python -m evals.run_eval` (needs a real key; not part of
  `make test`/`make verify`).
- Add `evals` to `lint-py` scope (`ruff check src tests evals`).

### 4.3 Case schema (hermetic, adversarial)

```python
class Trap(BaseModel):
    id: str
    kind: Literal["missing_skill", "adjacent_skill", "inflatable_metric", "seniority_inflation"]
    forbidden_terms: list[str]      # the final resume must NOT contain/claim these
    description: str
    probe_claim: str                # one deliberately unsupported claim for fact-check
    probe_provenance: str           # existing source Bullet id that does not support probe_claim

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
profile, an adjacent-but-different skill, a metric tempting to inflate, or a seniority the profile
doesn't support. The runner builds a minimal counterfactual resume from `probe_claim` and the
referenced source bullet. The provenance id must resolve, but that fact must not support the claim.
Seed validation proves that the claim contains a forbidden term and the provenance id exists.

`id`, trap ids, and `profile_ref` are restricted to simple slug characters; `profile_ref` cannot
contain path separators. Rubrics and forbidden-term lists are non-empty, and blank terms are
rejected at load time.

### 4.4 The two signals per run (the meta-eval)

**Deterministic (no model) — reproducible mechanical checks:**
- `trap_avoided` — final resume free of every trap's `forbidden_terms` (term + light normalization).
- `provenance_ok` — reuse `check_provenance`.
- `must_cite_covered` — every expected provenance id present in the output's `referenced_ids`.
- `budget_ok` — output honors the hard `max_experiences` and `max_bullets_per_role` limits;
  `target_total_bullets` is reported as a target, not treated as a hard maximum.

Trap terms are hand-authored case assertions, not a universal truth detector. Case review must
exclude ambiguous terms or contexts where merely mentioning the term would be truthful.

**Judge (separate premium agent, profile- and trap-blind):** input = final resume + JD + rubric.
The quality judge must not receive the profile, trap descriptions, forbidden terms, deterministic
check results, or panel scores; otherwise `panel_agreement` becomes contaminated by leaked ground
truth. Output:

```python
class DimensionScore(BaseModel):
    dimension: str
    score: int          # 0-100
    rationale: str
class JudgeVerdict(BaseModel):
    output_quality: int          # 0-100 overall
    dimensions: list[DimensionScore]
    summary: str
```

The harness rejects a verdict unless it contains exactly one score for every requested rubric
dimension, with no duplicates or unrequested dimensions.

Profile- and trap-blind on purpose: the judge grades **quality**, not fact-lock. Fact-lock is owned
by deterministic checks and the in-loop fact-check reviewer; asking the quality judge to re-derive
it would add a second unvalidated fact-checker and bias the quality score.

**Reviewer efficacy (computed across cases) — this is what makes "improve the agents" actionable:**
- `trap_recall` — run the configured **fact-check** reviewer once against each case's isolated
  generated probe resume; recall is the fraction of completed probes that produce a blocking
  issue. Because each probe contains exactly one planted unsupported claim, an unrelated issue
  cannot receive credit.
  Probe-call failures are retained with `detected=null`, excluded from the denominator, and reported
  as coverage failures without discarding the real tailoring/judge result.
  Organic trap appearances in real rounds remain visible in captured round artifacts but are not
  used as the recall denominator.
- `panel_agreement` — correlation of each reviewer's score on the **same final draft** with the
  judge's `output_quality` across cases. If the final round skipped the panel because provenance
  failed, that case is unpaired for panel agreement; never reuse a stale earlier-round score. A
  reviewer whose score doesn't track quality is miscalibrated → names the Phase 2 target.
- `convergence` — rounds-to-pass distribution, and whether the aggregate score **improved or
  regressed** across rounds where the scored panel actually ran. Provenance-only rounds have no
  comparable aggregate score; the runtime's placeholder zero must be recorded as `None`, not a
  quality regression. This is direct evidence motivating Phase 1's keep-best-round.

`runner.py` captures **all** `TailorRound`s — `run_tailor_review` already returns the full list, so
per-round critiques remain available for convergence and follow-up diagnostics with **no change to
the loop**. Probe reviews call the existing fact-check reviewer directly with the same evidence
input used by the panel; they do not mutate the tailoring loop.

**Usage and cost:** wrap each existing `Runner` in an eval-only metering decorator. The decorator
delegates `run`/`arun`, observes Agno's returned `RunOutput.metrics`, and accumulates input/output/
cache tokens, duration, call count, and provider-reported cost without changing agent behavior.
Missing provider cost is reported as `unknown`; never invent a dollar estimate from call count.
Calls that raise before returning a `RunOutput` are counted as failed attempts, but their token/cost
usage is marked unavailable because Agno exposes no completed metrics object to the decorator.

### 4.5 Judge anchoring (one-time human gate)

Run the live tier once; the user human-rates ~5 final resumes against the same JD and rubric while
blind to profile facts, traps, panel scores, and judge scores. Compare to the judge's
`output_quality`. If mean absolute error < ~10 and no individual error exceeds 20, the judge is
trusted and the result is recorded in
`evals/CALIBRATION.md` (cases rated, human scores, judge scores, MAE, judge model + prompt hash).
Re-run the anchor only when the judge prompt or model changes. Deliberately not automated: an
unvalidated judge is the disease this phase cures, so a human signs off once.

### 4.6 Offline tier scope (honest)

With faked agents there is no real quality to measure, so the CI tier tests the **harness's own
logic**, deterministically:
- the trap-checker flags a resume containing a forbidden term and passes a clean one;
- `metrics.py` computes `panel_agreement` / `convergence` on scripted rounds and scores, and
  `trap_recall` on scripted controlled-probe results;
- the case loader validates / round-trips `EvalCase` JSON, and rejects malformed cases.

Richer loop-invariant tests (keep-best-round, idempotent revision) land **with Phase 1**, since
they assert behavior Phase 1 introduces.

### 4.7 CLI / run flow (`run_eval.py`)

Load the configured style guide and build the **same** tailor bundle as production once, outside the
case loop. `--model <id>` overrides writer, reviser, reviewers, judge, and optional extractor;
otherwise normal tier routing applies. Per case: use embedded criteria, or call the real extract
agent when `--live-criteria` is set or criteria are absent → meter `run_tailor_review(...)` while
capturing all rounds → run deterministic checks → run isolated fact-check probes → judge the final
content → persist the partial result. A case failure is recorded and later cases continue unless
`--fail-fast` is set, so a late transient failure does not discard earlier paid work.

`report.py` renders a per-case table, failures, aggregate quality, fact-check probe recall,
per-reviewer agreement, per-case convergence, token/cost totals, model ids, config/style-guide
hashes, git commit, and judge prompt hash. The CLI checkpoints both
`evals/reports/<timestamp>.md` and a sibling JSON
artifact containing final resumes, all rounds/critiques, probes, usage, metadata, and failures after
every case; calibration and later comparisons use the JSON artifact. It echoes markdown to console.
Flags:
`--cases <dir>`, `--profiles <dir>`, `--config <path>`, `--out <path>`, `--model <id>`,
`--live-criteria`, `--limit N`, and `--fail-fast`. Empty case sets and non-positive limits are errors.

Agents are reused across cases for performance, but remain stateless (`db=None`, no history/memory).
If production later enables agent persistence, the eval must pass a unique case session id or build
an explicit reset seam before reuse.

### 4.8 Resolved leanings

1. **Criteria source:** embed `JobCriteria` in each case by default (isolates the tailor/review
   loop, deterministic input); `--live-criteria` also exercises the extract agent.
2. **Cost capture:** Agno 2.6.12 returns `RunOutput.metrics` with token, cache-token, duration, and
   provider-cost fields. Capture it with eval-only runner decorators. When a provider omits cost,
   or a call raises before returning metrics, report the coverage gap and `cost: unknown`; do not
   use a misleading call-count proxy.
3. **Seed size:** 8 cases (~2 per trap kind) to keep authoring honest and the first paid run cheap,
   then grow.
4. **Agno eval helpers:** keep the repository's `Runner` seam and custom resume-specific schemas
   instead of wrapping the workflow in `AccuracyEval`/`AgentAsJudgeEval`. Those helpers do not
   replace deterministic provenance/budget checks, controlled fact-check probes, or per-round
   reviewer correlation. Agno remains the agent runtime and `RunOutput.metrics` source.

## 5. Testing

- **Offline (CI, `make test-py`):** focused tests for schema/loader, trap scanning, probe recall,
  deterministic metrics, usage collection, runner orchestration, report contents, CLI flags and
  failure persistence. Every runner is scripted/faked; no model and no network.
- **Live (opt-in, `make eval`):** the real harness; not part of CI. Its "test" is the human anchor
  in `CALIBRATION.md` plus the generated report.

## 6. Success criteria

- `make eval` runs all seed cases through the real loop and emits a report with: per-case
  `output_quality`, deterministic pass/fail, `trap_recall`, `panel_agreement` per reviewer,
  convergence (rounds + improved/regressed), tokens, and provider-reported cost or `unknown`.
- A machine-readable sibling artifact preserves final resumes, round evidence, metadata, failures,
  and usage after each case so calibration and regression comparison are auditable.
- The report **names the weakest reviewer** only when enough observations exist; otherwise it says
  `insufficient data`. Fact-check is ranked by controlled-probe recall, not unrelated round issues.
- `make test-py` stays fully offline and green, with new machinery tests included.
- `CALIBRATION.md` records a judge anchored to <10 MAE with no individual error >20.
- Zero changes to `src/resume_tailor_harness/tailor/` behavior (observation-only phase).

## 7. Implementation constraints resolved by review

- Agno uses `RunOutput` in 2.6.12; its `metrics` object is the metering source.
- Trap matching uses Unicode case-folding plus escaped token boundaries; blank terms are invalid.
- `panel_agreement` requires at least five paired observations and non-zero variance. Below that,
  report `insufficient data` and do not name a weakest score-based reviewer.
- Fact-check recall also requires at least five controlled probes before it participates in the
  weakest-reviewer ranking.
- Embedded `JobCriteria` must be realistic and consistent with the JD; `{}` is not an acceptable
  seed shortcut because it no longer isolates a production-equivalent loop input.
