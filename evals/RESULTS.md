# Eval Results Log

## 2026-07-27 tailor scoring + fact-lock repair — PRE-CHANGE BASELINE

Production baseline from `scripts/tailor_health.py` against the workspace DB
(77 versions, 26 jobs) immediately before the repair branch. This is the
reference point for re-measuring; **no eval arms have been run yet.**

| metric | value |
| ------ | ----- |
| zero scores | 19 / 77 (all with `critiques == ['provenance']`) |
| unscored (`review_score IS NULL`) | 0 |
| gate failures — provenance | 19 |
| gate failures — fact-check | 50 |
| fact-check blocking issues | metric/number 53 · summary 31 · skill 28 · scope 17 · other 13 |
| reviewer means | ats-keyword 55.1 · hiring-manager 51.7 · recruiter 61.5 · concision 76.7 |
| jobs reaching `score_threshold: 85` | 0 / 26 |

Round-over-round transitions as the script counts them (all pairs):
improved 30, regressed 19, same 2. **Excluding pairs that touch a fabricated
`0`** — the 19 rounds where the panel was skipped — it is improved 16,
regressed 13, mean delta **+0.8**. The second figure is the one that shows the
revise loop was a coin flip; the first is what the script will keep reporting,
since a fabricated `0` is no longer reachable after this change.

**Still outstanding — Phase D of the plan.** `score_threshold` (85) and
`match_plan_enabled` (false) are deliberately unchanged. Deciding them requires
the eval arms below, none of which have been run:

| arm | config | status |
| --- | ------ | ------ |
| `before` | `dev` | not run |
| `phaseAB` | scoring + fact-lock fixes | not run |
| `phaseC` | + reviser JD, best-round base | not run |
| `bands` | + `score_bands` | not run |
| `matchplan` | `config/review.match_plan.yaml` | not run |

Per `evals/CALIBRATION.md` the judge is still un-anchored (stand-in only), so
when these run, only **relative** arm-to-arm deltas may be claimed.

## 2026-07 craft prompt enrichment

**Decision:** Live after-arm cases were skipped at user direction. No
ship/iterate/revert conclusion was inferred from partial data, and the
match-plan default remains unchanged.

## 2026-07 cover-letter baseline (measure-only)

| metric                     | value |
| -------------------------- | ----- |
| mean quality               | 77.5  |
| trap_ok (cases with traps) | 2/3   |
| provenance_ok              | 4/4   |
| revise rounds fired        | 0     |

No gate: this baseline exists so future cover-letter prompt changes have a
reference point. **Artifact:** `evals/reports/2026-07-cl-baseline.json`

## 2026-07 resume baseline

| metric                     | value                       |
| -------------------------- | --------------------------- |
| mean quality               | 46.0                        |
| trap_ok (cases with traps) | 12/12                       |
| provenance_ok              | 12/12                       |
| judge model                | deepseek:deepseek-v4-pro    |
| judge prompt sha256        | 64ed837a3ed9c1809441f026ed6581623a7697fd92fc2ed14b5db733c34ce8bd |

No gate: this is the reference point for future resume prompt changes. The
current-schema, zero-failure 12-case report was promoted after verifying the
case set, config, style guide, judge model, and judge prompt hashes against the
current eval harness. **Artifact:** `evals/reports/2026-07-resume-baseline.json`

The live profile checkpoint produced 70 grouped matrix rows: 0 missing
assignments and 1 explicit `other` assignment (`vFlash`, 1.4%).

## 2026-08-04 deterministic fact-lock gates + must-have coverage

Ships `skill-naming` and `numeric-evidence` as deterministic gates and wires the
already-computed `SkillMatchContext` into the writer, reviser, and advisory
panel. `score_threshold: 85` and `match_plan_enabled: false` remain untouched —
the Phase D arms below are still unrun.

Pre-change reference is the 2026-07-27 baseline above (77 versions / 26 jobs,
8/77 gate-clean, ats-keyword mean 55.1, 0/26 jobs reaching threshold).

Re-measure with `python scripts/tailor_health.py <workspace-db>` after a tailor
run of comparable size and fill in:

| metric | before | after |
| ------ | ------ | ----- |
| gate-clean rounds | 8 / 77 | |
| gate failures — fact-check | 50 | |
| gate failures — skill-naming | n/a | |
| gate failures — numeric-evidence | n/a | |
| ats-keyword mean | 55.1 | |
| must-have-coverage mean | n/a | |

Success criteria from the spec: zero rounds failing on a compound skill entry;
the fact-check metric/number bucket falls; the ats-keyword mean rises **without**
fact-check failures rising; remaining fact-check failures concentrate in
scope-creep claims.

## 2026-08-08 evidence-portfolio tailoring — implementation checkpoint

The portfolio arm and its measurement fields are implemented, but no live A/B
or blind comparison has been run. The shipped fast and deep configurations
therefore remain `evidence_portfolio_enabled: false`. The legacy
`match_plan_enabled` spelling is accepted for one release only.

The eval corpus now labels six selection risks: competing roles, stronger
projects, career-change evidence, overlong profiles, direct-versus-adjacent
skills, and safe alias paraphrasing. Reports record mandatory-evidence recall,
forbidden selection/highlight hits, planner fallback rate, measured tailoring
latency, calls, token usage, and provider cost. The deterministic fallback gate
is exercised offline; live results must be recorded as artifacts, not inferred
from that unit gate.

Run both arms with the same explicit model and preserve both Markdown and JSON
artifacts:

```powershell
python -m evals.run_eval --config config/review.yaml.example --model <model> --out evals/reports/<stamp>-baseline.md
python -m evals.run_eval --config config/review.match_plan.yaml --model <model> --out evals/reports/<stamp>-portfolio.md
```

Activation remains blocked until the portfolio arm demonstrates all of:

- mean relevance improvement of at least five points;
- at least 90% mandatory-evidence recall and zero forbidden/gap claims;
- no provenance, fact-lock, trap-recall, or forbidden-highlight regression;
- at least seven portfolio wins in a blind comparison of ten representative
  real jobs;
- acceptable latency, token cost, and fallback rate recorded in the artifacts.
