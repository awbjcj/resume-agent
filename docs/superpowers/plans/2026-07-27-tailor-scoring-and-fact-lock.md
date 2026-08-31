# Tailor Pipeline Repair & Improvement Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the four defects that make the tailor report a fabricated `0` and mislabel it as a fact-check failure, then repair the five process defects that make the review loop unable to converge — without loosening fact-lock by a single claim.

**Architecture:** The symptom the user reported ("score is always 0, fact-check always fails") is one mislabelled event with a structural cause: `verdict.aggregate` *defines* the score as `0` when no advisory reviewer ran, and `workflow` skips the panel whenever the deterministic provenance gate fails. Underneath it sits a review loop that cannot converge: the reviser is blind to the job description while being asked to fix job-relevance issues, five reviewers score on five private scales against one fixed threshold, and each revision builds on the last round even when that round regressed. The repair is structural at every layer — make the invalid state unrepresentable (a `renderable_profile` writer projection, a `summary_provenance` field) rather than asking a model to remember a rule, and give each agent the input its job actually requires.

**Tech Stack:** Python 3.12, FastAPI, SQLModel/SQLAlchemy, Pydantic v2, pytest. Web: React 19, TypeScript, TanStack Query, Base UI, Vitest + Testing Library.

---

## Evidence This Plan Is Built On

Measured against `data/users/1398ad91b2b2/resume_tailor_harness.db` (77 `resume_versions`, 26 jobs) and the shipped configs, 2026-07-27. Every row was reproduced, not inferred.

### Scoring and the gate

| Observation | Value |
|---|---|
| Versions scored exactly `0` | 19 / 77 (25%) |
| …whose `critique_json` contained **only** `provenance` | **19 / 19 (100%)** |
| Provenance issues that were `inferred soft/domain skills cannot be rendered` | 20 / 25 |
| Rounds that reached the panel | 58 |
| …that failed the `fact-check` reviewer | 50 / 58 (86%) |
| Blocking fact-check issues by kind | invented metric 56 · summary claim 31 · skill broadening 25 · scope/wording 17 · other 13 |
| Jobs whose final round reached `score_threshold: 85` | **0 / 26** |

```python
prov_fail = ReviewCritique(reviewer="provenance", score=0, passed=False, issues=[...])
aggregate([prov_fail], cfg).aggregate_score                 # -> 0
aggregate([prov_fail, fc_100, *four_advisory_at_95], cfg)   # -> 95
```

The `0` is `total_weight == 0`, not a quality judgement.

### The revision loop does not converge

| Observation | Value |
|---|---|
| Round-over-round transitions (excluding rounds where the panel was skipped) | 29 |
| improved / regressed / same | **16 / 13 / 0** |
| Mean score delta per revision | **+0.8** (min −24, max +21) |
| Gate transitions dirty→clean | 5 |
| Gate transitions **clean→dirty** | **5** |

A revision costs one LLM call per job per round and is, measurably, a coin flip.

### Calibration and dead configuration

| Observation | Value |
|---|---|
| Mean advisory scores | ats-keyword 55.1 · recruiter 61.5 · hiring-manager 51.7 · concision 76.7 |
| `score_bands` enabled on any reviewer, either shipped config | **no** (feature built, `_SCORE_BAND_INSTRUCTION` exists) |
| `match_plan_enabled` in either shipped config | **no** (only in `config/review.match_plan.yaml`) |
| `early_stop_on_regression` in `review_deep.yaml` | **false** (13 regressions observed) |
| Recorded eval baseline (`evals/RESULTS.md`) | mean quality **46.0**, trap_ok 12/12, provenance_ok 12/12 |

### The nine defects

| # | Defect | Where | Cost |
|---|---|---|---|
| D1 | Score is `0` when no advisory reviewer ran | `tailor/verdict.py:43` | 19 fabricated zeros |
| D2 | Panel skipped on provenance failure → reviser gets no quality feedback | `tailor/workflow.py:95,169` | 25% of rounds blind |
| D3 | Writer is handed inferred soft/domain skills it may not render, unmarked and uninstructed | `tailor/tailoring.py:28`, `tailor/agents.py` | 20 of 25 provenance failures |
| D4 | `summary` is the only fact-locked field with no provenance; reviewer sees only facts cited *elsewhere* | `models/resume.py` | 31 blocking issues, some false |
| D5 | Writer licensed to "normalize" skill names; reviewer instructed to fail added technology | `tailor/agents.py` | 25 blocking issues |
| D6 | **Reviser never receives the job description** — yet must fix `ats-keyword` and `hiring-manager` issues | `tailor/tailoring.py:48` | +0.8 mean delta |
| D7 | Five reviewers, five private scales, one fixed threshold of 85 | both shipped configs | 0/26 ever passed |
| D8 | Revision always builds on the last round, even a regressed one | `tailor/workflow.py:119,195` | 13 regressions compound |
| D9 | `early_stop_on_regression: false` in deep mode | `config/review_deep.yaml` | 3 rounds burned regardless |

> **D6 is an asymmetry inside this codebase, not an oversight in general.** `cover_letter/service.py:39` calls its own `compose_revise_input(content, bad, profile_facts, job.jd_text)` — the cover-letter reviser *does* get the job. Only the resume reviser is blind.

---

## Global Constraints

- **Fact-lock is not being loosened.** Every claim must still trace to a fact in `facts.json`. The 142 blocking fact-check issues were, on inspection, *correct* — the writer really did invent metrics ("saving hours of manual reporting effort" against a fact with no stated outcome) and broaden skills (`Data Pipelines` cited to a fact named *Configurable Batch Pipelines*). This plan removes the false positives and the contradictory instructions, and makes true positives less likely to be generated. `reviewer-fact-check` remains the only non-editable integrity gate.
- **Branch:** `fix/tailor-scoring-and-fact-lock`, off `dev`. Never commit to `main`.
- **Tests are offline.** No API key, no network; all agents and Playwright are faked. Run `.venv/Scripts/python.exe -m pytest`.
- **Lint:** `ruff check` must pass before every commit (`make lint-py` covers `src tests evals`).
- **Wire format is camelCase.** Schema changes require `bash scripts/gen_ts_client.sh`; `tests/api/test_openapi_contract.py` is the drift gate.
- **Every task ends green and commits independently.**
- **No prompt-only fix where a structural one exists.** If a rule can be enforced by a type or an input projection, the instruction is a supplement, never the mechanism.
- **Config changes are measured, not guessed.** Phase D changes `config/review.yaml` only against eval evidence produced in Task 14.

## Non-Goals

- Retro-fixing the 77 existing `resume_versions` rows. They are historical records.
- Changing the merged-advisory design, the connector layer, or discovery fit scores.
- Anchoring the eval judge to a human rater (`evals/CALIBRATION.md` is explicit that this is outstanding). This plan uses the judge for **relative A/B only**, which its stand-in calibration supports; no absolute quality claim may be made from it.

---

## File Structure

**Modified backend files**

| Path | Change |
|---|---|
| `src/resume_tailor_harness/tailor/verdict.py` | `aggregate_score: int \| None`; `None` means "no advisory bar ran", never `0`. |
| `src/resume_tailor_harness/tailor/workflow.py` | Panel always runs; citation-slip free retry; revise from the best round. |
| `src/resume_tailor_harness/tailor/provenance.py` | `renderable_profile()` projection; `summary_provenance` joins the checked uses. |
| `src/resume_tailor_harness/tailor/tailoring.py` | Writer/reviser inputs use `renderable_profile`; **reviser receives `jd_text`**. |
| `src/resume_tailor_harness/tailor/agents.py` | Inferred-skill rule; normalization contradiction resolved; outcome rule; summary rule. |
| `src/resume_tailor_harness/tailor/review_config.py` | `provenance_retry_budget: int = 1`. |
| `src/resume_tailor_harness/tailor/service.py` | Persists `review_score=None` correctly. |
| `src/resume_tailor_harness/models/resume.py` | `ResumeContent.summary_provenance: list[str]`. |
| `src/resume_tailor_harness/tracking/repository.py` | `_score_key` orders `None` last. |
| `src/resume_tailor_harness/api/schemas/jobs.py` | `ResumeVersionOut.failed_gates: list[str]`. |
| `src/resume_tailor_harness/api/routers/jobs.py` | Project `failed_gates` from `critique_json`. |
| `config/review.yaml.example`, `config/review_deep.yaml.example` | `score_bands: true`; deep gains `early_stop_on_regression: true`. |

**Modified web files**

| Path | Change |
|---|---|
| `web/src/features/job/VersionRow.tsx` | Badge names the gate that actually failed; `null` score renders "not scored". |

**New files**

| Path | Responsibility |
|---|---|
| `tests/test_tailor_review_e2e.py` | End-to-end faked-agent guard for the whole loop. |
| `web/src/features/job/VersionRow.test.tsx` | Badge and score rendering. |
| `scripts/tailor_health.py` | Read-only report over `resume_versions`: score distribution, gate failures by gate, issue kinds. |

---

# Phase A — Stop reporting fiction

*Fixes D1, D2. After this phase the reported score is always a real measurement or an explicit "not scored".*

## Task 1: The score is unknown, not zero

**Files:** modify `src/resume_tailor_harness/tailor/verdict.py`, `src/resume_tailor_harness/tracking/repository.py` · test `tests/test_tailor_verdict.py`

**Step 1 — Failing tests.**
- [ ] `aggregate([provenance_fail], cfg).aggregate_score is None`.
- [ ] `aggregate([prov_ok, fc_ok, *advisory_95], cfg).aggregate_score == 95` — unchanged.
- [ ] A config with only gate reviewers yields `aggregate_score is None` and `passed == gate_passed` — no advisory bar means the gate alone decides.
- [ ] `pick_best` ranks a scored version above a `None`-scored one regardless of `created_at`.

**Step 2 — Implement.**
- [ ] `PanelVerdict.aggregate_score: int | None`; `= round(...) if total_weight else None`.
- [ ] `passed = gate_passed and (aggregate_score is None or aggregate_score >= config.score_threshold)`.
- [ ] `_score_key` sorts `None` last: `(score is not None, score)`.
- [ ] `_has_regressed` ignores `None`-scored rounds when computing `best_prior_score`, and never reads "scored → unscored" as a numeric regression.

**Note:** `evals/metrics.py:46` already declares `RoundRecord.aggregate_score: int | None` — the eval harness anticipated this; only the runtime disagreed. `services/revision.py:56` also already writes `None` for this case. This task makes the third writer agree with the other two.

## Task 2: The panel always runs

**Files:** modify `src/resume_tailor_harness/tailor/workflow.py` · test `tests/test_tailor_workflow.py`

The skip saved one merged advisory call and cost a blind revision on 25% of rounds.

**Step 1 — Failing tests.**
- [ ] A provenance-failing draft still produces advisory critiques and a real `aggregate_score`.
- [ ] `verdict.gate_passed is False` and `verdict.passed is False` for that round. **Fact-lock regression guard.**
- [ ] The revise input for that round contains the provenance blocking issue *and* the advisory issues.
- [ ] Same assertions for `arun_tailor_review`.

**Step 2 — Implement.**
- [ ] Delete the `if provenance.passed:` branch in both loops; always `critiques = [provenance, *panel]`.

## Task 3: A citation slip does not consume a round

**Files:** modify `src/resume_tailor_harness/tailor/workflow.py`, `src/resume_tailor_harness/tailor/review_config.py` · test `tests/test_tailor_workflow.py`

**Step 1 — Failing tests.**
- [ ] Provenance fails round 1, everything passes round 2 → a **third** round runs despite `max_rounds: 2`.
- [ ] The free retry is granted at most `provenance_retry_budget` times; three consecutive provenance failures still terminate.
- [ ] A round failing provenance *and* the advisory bar consumes a round normally.
- [ ] `provenance_retry_budget: 0` reproduces today's counting exactly.

**Step 2 — Implement.**
- [ ] `ReviewConfig.provenance_retry_budget: int = Field(default=1, ge=0)`.
- [ ] Track `free_retries_used` in both loop bodies.

> **⚑ Your input wanted here.** The predicate deciding when a round is "only a citation slip" is a policy judgement that governs how much LLM budget a bad draft can burn — not boilerplate. Write `_is_citation_slip` in `src/resume_tailor_harness/tailor/workflow.py`; the signature and docstring will be prepared for you:
>
> ```python
> def _is_citation_slip(verdict: PanelVerdict, config: ReviewConfig) -> bool:
>     """True when this round failed ONLY because provenance ids were wrong.
>
>     A citation slip is cheap to fix and should not cost one of the
>     `max_rounds` quality passes. A resume that is *also* below the advisory
>     bar is not a slip - it needs a real revision round, and a free retry
>     just spends tokens.
>
>     Trade-offs to weigh:
>       - Strict (advisory must already clear `score_threshold`): safest on
>         budget, but almost never fires - observed advisory means are 51-77
>         against a threshold of 85.
>       - Loose (provenance is the only failing gate, whatever the score):
>         always fires on a slip, but a weak resume also gets a free round.
>       - Middle: provenance is the only failing gate AND `aggregate_score`
>         is not None, i.e. the panel genuinely ran and produced feedback.
>     """
> ```
>
> `verdict.gate_passed` is the AND of all gates, so you must inspect the individual gate critiques in `verdict.critiques` to tell provenance apart from fact-check.

---

# Phase B — Stop generating violations

*Fixes D3, D4, D5. After this phase the writer cannot cite a forbidden fact, the summary is checkable, and no two agents hold contradictory rules.*

## Task 4: The writer never sees a fact it may not render

**Files:** modify `src/resume_tailor_harness/tailor/provenance.py`, `src/resume_tailor_harness/tailor/tailoring.py` · test `tests/test_tailor_provenance.py`, `tests/test_tailor_tailoring.py`

`provenance.py:90` forbids rendering an inferred skill whose `category != "hard"`. The evidence profile contains six — `Stakeholder Communication`, `Mentoring`, `Issue Triage`, `SOP Development`, `NHTSA Regulations`, `Human Factors Engineering` — every one an obvious resume line, dumped to the writer unmarked. This single mismatch caused 20 of 25 provenance failures.

**Step 1 — Failing tests.**
- [ ] `renderable_profile(facts)` drops inferred skills with `category != "hard"` and leaves every other section byte-identical under `model_dump()`.
- [ ] It keeps inferred **hard** skills and their `evidence_fact_ids` targets resolvable.
- [ ] `compose_tailor_input` / `compose_revise_input` output contains no dropped id.
- [ ] `check_provenance` still indexes the **full** facts, and an inferred non-hard id arriving by any other path still fails. **Regression guard: the gate is not relaxed, only the writer's menu is narrowed.**

**Step 2 — Implement.**
- [ ] `renderable_profile(facts: ProfileFacts) -> ProfileFacts` in `provenance.py` (it owns the rule, so it owns the projection).
- [ ] Both compose functions dump `renderable_profile(profile_facts)`.
- [ ] Leave `compose_match_plan_input` alone — CLAUDE.md is explicit that inferred skills legitimately guide match-plan emphasis.

**Verification:** against the real profile, 341 → 335 skills, exactly the six named above removed.

## Task 5: The summary becomes checkable

**Files:** modify `src/resume_tailor_harness/models/resume.py`, `src/resume_tailor_harness/tailor/provenance.py` · test `tests/test_tailor_provenance.py`, `tests/test_models_resume.py`

`summary` is bare `str | None`, so the gate cannot see it and `resolve_evidence` ships the reviewer only facts cited by *other* sections — a true summary claim whose supporting fact is not otherwise cited is structurally guaranteed to read as unsupported.

**Step 1 — Failing tests.**
- [ ] `summary_provenance=["missing"]` produces a `missing` entry from `check_provenance`.
- [ ] `referenced_ids` includes summary ids; `resolve_evidence` ships their facts to the gate reviewer.
- [ ] A summary citing an **inferred** id fails — inferred facts justify skills entries only.
- [ ] `summary=None` with empty `summary_provenance` passes; a non-empty summary with empty `summary_provenance` is **allowed** (old stored `content_json` must still validate) but yields no new evidence.

**Step 2 — Implement.**
- [ ] `summary_provenance: list[str] = Field(default_factory=list)` on `ResumeContent`.
- [ ] `_referenced_uses` yields `(fact_id, "entity")` per summary id — "entity" use means the existing branch already rejects an inferred pointer there; no new rule.

**Verification:** all 77 stored `content_json` blobs still validate.

## Task 6: The writer and the reviewer stop contradicting each other

**Files:** modify `src/resume_tailor_harness/tailor/agents.py` · test `tests/test_prompt_registry.py`, `tests/test_agent_prompt_contracts.py`, `tests/test_tailor_agents.py`

Three instruction defects, in descending measured cost:

1. **Invented metrics (56).** The writer is told not to invent *metrics* but not that a qualitative outcome — "saving hours of manual reporting effort" — is equally unsupported when the fact records only an activity.
2. **Summary (31).** No instruction to populate `summary_provenance`.
3. **Skill broadening (25).** The writer may "normalize" a skill name; the reviewer must fail added technology. `Vehicle Log Signal Analysis` → `Log Analysis / Telemetry` satisfies A and violates B. **The reviewer is right; the writer's licence is the bug.**

**Step 1 — Failing tests.**
- [ ] Registry snapshots for `tailor-writer` and `tailor-reviser` contain the inferred-skill prohibition, the no-unsupported-outcome rule, and the `summary_provenance` requirement.
- [ ] No writer instruction permits normalization beyond casing, punctuation, or expanding an alias already listed on the fact.
- [ ] `reviewer-fact-check` instructions are **unchanged** — it is the non-editable gate and this task must not touch it.

**Step 2 — Implement.** In `_TAILOR_INSTRUCTIONS`, `_REVISER_INSTRUCTIONS`, and (where applicable) `_REVISION_INSTRUCTIONS`:
- [ ] Replace the normalization licence with: casing, punctuation, and aliases already on the fact only — never a broader or different technology.
- [ ] An inferred skill with `category` other than `hard` must never be cited as provenance and must not appear in the skills section. (Task 4 makes this unreachable; the instruction explains *why* if one arrives via a match plan or a revise critique.)
- [ ] State an outcome, benefit, saving, or improvement only when the source fact states it. If the fact records an activity, describe the activity.
- [ ] Every summary must list in `summary_provenance` the ids it draws on and claim nothing those facts do not support.

---

# Phase C — Make the revision loop earn its cost

*Fixes D6, D8, D9. Today a revision is a coin flip (+0.8 mean, 16 up / 13 down) that costs one LLM call per job per round.*

## Task 7: The reviser sees the job description

**Files:** modify `src/resume_tailor_harness/tailor/tailoring.py`, `src/resume_tailor_harness/tailor/workflow.py` · test `tests/test_tailor_tailoring.py`, `tests/test_tailoring.py`, `tests/test_tailor_workflow.py`

`compose_revise_input` takes no `jd_text`. The reviser is handed `ats-keyword` issues ("the resume does not cover the job's must-have terms") and `hiring-manager` issues ("the experience does not demonstrate the job's core responsibilities") and asked to fix them **without ever seeing the job**. Its own sibling — `cover_letter/drafting.compose_revise_input` — already receives `job.jd_text` at `cover_letter/service.py:39`.

**Step 1 — Failing tests.**
- [ ] `compose_revise_input(..., jd_text="...")` output contains a `JOB DESCRIPTION:` section.
- [ ] The JD is labelled as data, consistent with the writer's prompt-injection framing (`tests/test_prompt_injection.py` must still pass).
- [ ] Both `run_tailor_review` and `arun_tailor_review` thread `jd_text` into every revise call.
- [ ] The reviser instruction set states that the JD may steer selection and emphasis but can never establish a candidate fact — the same sentence the writer already carries.

**Step 2 — Implement.**
- [ ] Add `jd_text: str` to `compose_revise_input` (positional after `profile_facts`, mirroring the cover-letter signature so the two stay recognizably the same function).
- [ ] Pass `jd_text` at `workflow.py:119` and `workflow.py:195`.
- [ ] Add the JD framing sentence to `_REVISER_INSTRUCTIONS`.

**Expected effect:** this is the single highest-leverage change in the plan. Measure it as its own eval arm in Task 14.

## Task 8: Revise from the best round, not the last

**Files:** modify `src/resume_tailor_harness/tailor/workflow.py` · test `tests/test_tailor_workflow.py`

Today `content = revise(...)` always builds on the latest content, so a regressed round becomes the base for the next one and 13 observed regressions compound. `pick_best` already surfaces the best clean version to the user — the loop should optimize from the same place.

**Step 1 — Failing tests.**
- [ ] Round 2 scores lower than round 1 → round 3 revises from **round 1's** content, not round 2's.
- [ ] A gate-clean lower-scoring round never displaces a gate-dirty higher-scoring one as the base: gate-clean wins first, score second. (Same ordering `pick_best` uses; keep the two consistent.)
- [ ] With monotonically improving rounds, behaviour is byte-identical to today. **Regression guard.**
- [ ] `rounds` still records every round in order, including regressed ones — the history is not rewritten.

**Step 2 — Implement.**
- [ ] Extract the "best so far" selection into one helper shared in spirit with `tracking/repository.select_surfaced`; revise from its content.

## Task 9: Deep mode stops burning rounds on regressions

**Files:** modify `config/review_deep.yaml.example` · test `tests/test_shipped_review_configs.py`

- [ ] `early_stop_on_regression: true` in `review_deep.yaml.example` (fast mode already has it).
- [ ] Test asserts both shipped rosters enable it, and that `review.yaml.example` is unchanged in every other respect.
- [ ] Document in the file header that Task 8 makes early stop cheaper: the loop now stops *and* keeps its best round rather than its last.

---

# Phase D — Calibrate against evidence

*Fixes D7. Do not start this phase until Phases A–C are green and Task 14's baseline exists.*

## Task 10: One shared scoring scale

**Files:** modify `config/review.yaml.example`, `config/review_deep.yaml.example` · test `tests/test_shipped_review_configs.py`

`_SCORE_BAND_INSTRUCTION` already defines 90–100 ship-ready / 75–89 solid / 60–74 material gaps / <60 disqualifying. It is **disabled on every reviewer in both shipped configs**, so five reviewers score on five private scales and the mean is compared to a fixed 85.

**Step 1 — Failing tests.**
- [ ] Every non-gate reviewer in both shipped configs has `score_bands: true`.
- [ ] `build_reviewer_agent(..., score_bands=True)` includes `_SCORE_BAND_INSTRUCTION`; `False` omits it (existing behaviour, pinned).
- [ ] The gate reviewer `fact-check` keeps its own explicit scoring rule and is **not** given bands — its instruction already fixes `score=100` on pass.

**Step 2 — Implement.** Set `score_bands: true` on `ats-keyword`, `recruiter`, `hiring-manager`, `concision` in both `.example` files, and document that `config/review.yaml` is gitignored so existing installs need the section re-copied or reset via Settings.

## Task 11: Derive the threshold; decide the match plan

**Do not guess. This task consumes Task 14's output.**

- [ ] With Phases A–C plus Task 10 live, run the eval arms from Task 14 and read the new advisory score distribution.
- [ ] Choose `score_threshold` so that a resume the judge rates ≥75 passes and one it rates <60 does not. Record the derivation in `evals/RESULTS.md`. If the data says 85 is now right, **leave it at 85** and say so.
- [ ] Decide `match_plan_enabled` from the A/B arm, not from taste. `evals/RESULTS.md` already records that the previous attempt was abandoned with partial data and "the match-plan default remains unchanged" — either finish that measurement or leave the default alone again, explicitly.
- [ ] Re-evaluate `max_rounds` last: Task 3's free retry and Task 8's best-round base both change what a round is worth.

---

# Phase E — Honest surfaces and durable measurement

## Task 12: The badge names the gate that actually failed

**Files:** modify `src/resume_tailor_harness/api/schemas/jobs.py`, `src/resume_tailor_harness/api/routers/jobs.py`, `web/src/features/job/VersionRow.tsx` · test `tests/api/test_job_detail.py`, `web/src/features/job/VersionRow.test.tsx`

`tailor/service.py:72` writes `fact_check_passed = verdict.gate_passed` — provenance AND fact-check. `VersionRow.tsx:68` therefore renders **"Fact-check failed"** on 19 rounds where fact-check never ran. The column's meaning ("all gates clean") is correct and `pick_best` depends on it, so keep the column and the wire field; fix the label and add detail.

- [ ] `ResumeVersionOut.failed_gates: list[str] = []`, projected in the router from `critique_json`; `["provenance"]` vs `["fact-check"]` vs both; empty when clean.
- [ ] Badge reads "Fact-lock passed" / "Fact-lock failed — provenance" / "Fact-lock failed — fact-check".
- [ ] `reviewScore == null` renders "not scored" (the `?? "not scored"` path exists but is unreachable from the tailor path today).
- [ ] `bash scripts/gen_ts_client.sh`; contract drift gate passes.

**Verification:** `pytest`, and in `web/`: `npm run test`, `npm run lint`, `npx tsc --noEmit`.

## Task 13: End-to-end guard

**Files:** create `tests/test_tailor_review_e2e.py`

- [ ] A writer fed `renderable_profile` output cannot cite an inferred soft/domain id — assert the id is absent from the writer's input JSON.
- [ ] A full faked run where round 1 fails provenance yields: a non-`None` score, `gate_passed=False`, a full advisory critique set, a free retry, and a final clean round.
- [ ] A faked writer that fabricates a metric **still fails the round**. This is the anti-regression test for the entire plan — if it ever passes, fact-lock has been broken.
- [ ] A faked reviser asserts it received the JD.

## Task 14: Measure, and keep measuring

**Files:** create `scripts/tailor_health.py`

The eval harness already exists (`make eval` → `evals/run_eval.py`, 12 cases, `--config` arm support, recorded baseline **mean quality 46.0 / trap_ok 12/12 / provenance_ok 12/12**). Use it rather than inventing a new one.

- [ ] `scripts/tailor_health.py`: read-only report over `resume_versions` — score distribution, `None` count, gate failures split by gate, blocking-issue counts by kind. The queries in the Evidence section above are its specification.
- [ ] Record the **pre-change baseline** from the current DB and the existing `evals/RESULTS.md` figures.
- [ ] Run these eval arms, each a `--config` variant, and record all of them in `evals/RESULTS.md`:
  1. `before` — current `dev`.
  2. `phaseAB` — Phases A + B.
  3. `phaseC` — plus the reviser JD (Task 7) and best-round base (Task 8). **Expect the largest single delta here.**
  4. `bands` — plus Task 10.
  5. `matchplan` — `config/review.match_plan.yaml` on top of the winner, to settle Task 11's open question.
- [ ] State plainly in `RESULTS.md` that the judge remains un-anchored per `evals/CALIBRATION.md`, so only **relative** arm-to-arm deltas are claimed.
- [ ] Re-tailor ≥10 real jobs on the fixed branch and re-run `tailor_health.py` to confirm the production numbers move with the eval numbers.

---

## Sequencing and stopping points

```
Phase A  1 → 2 → 3          (ordered; the scoring loop)
Phase B  4, 5 independent → 6   (6 needs 4 and 5 for two sentences)
Phase C  7, 8 independent → 9
Phase E  12 (needs 1) · 13 (needs A+B+C) · 14 (needs 13)
Phase D  10 → 11            (LAST: 11 consumes 14's output)
```

- **Tasks 1, 2 and 4 alone remove the symptom you reported.** The zeros disappear and the dominant provenance failure stops occurring. That is a legitimate ship point.
- **Tasks 5–7 are what actually raise the fact-check pass rate.** Task 7 is the highest-leverage single change in the plan.
- **Phase D must come last.** Changing the threshold before the loop is fixed would calibrate against a distribution polluted by fabricated zeros, blind revisions, and five private scales.

## What this plan deliberately does not promise

Invented metrics were 56 of 142 blocking issues — the largest single bucket. Tasks 6 and 7 will reduce them; they will not eliminate them, because that failure is genuine model behaviour and catching it is exactly what the gate is for. A fact-check pass rate approaching 100% would be evidence the gate had been weakened, not that the writer had improved. **Task 13's fabricated-metric test exists to keep that honest.**
