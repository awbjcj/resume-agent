# Evaluating agent quality

How to measure whether this project's agents are actually good, and what the
numbers are allowed to mean. Design rationale lives in
[the Phase 0 spec](../docs/superpowers/specs/2026-06-29-agent-quality-eval-harness-design.md);
recorded measurements live in [RESULTS.md](RESULTS.md); judge trust lives in
[CALIBRATION.md](CALIBRATION.md).

## Pick the right instrument

| Question | Run |
| --- | --- |
| Did I break the eval harness itself? | `pytest tests/eval` (free, offline, in CI) |
| Did a prompt/config change move resume quality? | `make eval` |
| Did a change move cover-letter quality? | `python -m evals.run_cl_eval` |
| Does Scout still resolve companies to the right ATS board? | `python evals/run_scout_source_eval.py` |
| How is tailoring doing on *real* user data, not synthetic cases? | `python scripts/tailor_health.py <workspace-db>` |

The first is free. The rest cost real API calls, and the Scout one makes live
network requests to third-party career sites.

## Why the tiers are split this way

The live tier lives **outside** `tests/` on purpose: `make test-py` collects
only `tests/`, so no CI run can ever make a paid call. The offline tier lives
**under** `tests/` so it runs automatically. With faked agents there is no real
quality to measure, so `tests/eval/` asserts the *harness's own* logic — that
the trap checker flags a forbidden term, that `correlation` / `convergence` /
`trap_recall` compute correctly on scripted inputs, that malformed cases are
rejected. Passing `tests/eval` says nothing about agent quality.

## Prerequisites for the live tier

1. An API key in `.env` for whichever provider your tiers name
   (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `DEEPSEEK_API_KEY`).
2. `CHEAP_MODEL` / `MID_MODEL` / `PREMIUM_MODEL` set, or accept the defaults in
   `config.py` (`claude-haiku-4-5` / `claude-sonnet-5` / `claude-opus-5`).
3. A review config. `config/review.yaml` is gitignored, so `run_eval` falls back
   to `config/review.yaml.example` automatically when it is absent.

Budget expectation: 14 resume cases, each running tailor + up to two rounds of
panel + reviser + judge + one fact-check probe. Use `--limit` while iterating.

## Resume quality

```bash
make eval
```

Explicit form, which is what you want for anything you intend to record:

```bash
uv run python -m evals.run_eval --config config/review.yaml.example --model deepseek:deepseek-v4-pro --out evals/reports/20260827T000000Z-baseline.md
```

| Flag | Effect |
| --- | --- |
| `--cases` / `--profiles` | Case and profile directories (default `evals/cases`, `evals/profiles`) |
| `--config` | Review config; falls back to `<name>.example` if the file is absent |
| `--model` | Pin **every** agent to one model id — see the sharp edge below |
| `--limit N` | First N cases only |
| `--out` | Markdown path; the JSON artifact is written alongside with a `.json` suffix |
| `--live-criteria` | Always call the extract agent instead of using each case's embedded `criteria` |
| `--fail-fast` | Stop at the first case that raises |

Both artifacts are rewritten in a `finally` after **every** case, so a crash or
an interrupt twelve cases in still leaves a valid partial report on disk. Exit
code is 1 if any case raised; the failures are listed at the bottom of the
report.

Cases are adversarial by construction. Each of the 14 resume cases in
[cases/](cases) plants a trap — `missing_skill`, `adjacent_skill`,
`inflatable_metric`, or `seniority_inflation` — with hand-authored
`forbidden_terms`. Trap terms are case assertions, not a universal truth
detector: when adding a case, exclude any term whose mere mention could be
truthful.

## Cover letters

```bash
uv run python -m evals.run_cl_eval --limit 4
```

Measure-only, no gate. It reads the same `evals/cases` directory but keeps only
`target: cover_letter` cases (4 today), and reports `finalQuality`, `trapOk`,
`provenanceOk`, `reviseRounds`, and usage per case. The reference point is the
77.5 mean recorded in [RESULTS.md](RESULTS.md).

## Scout ATS source resolution

```bash
uv run python evals/run_scout_source_eval.py
```

No LLM judge — this one checks resolved board URLs against
[scout_source_cases.json](scout_source_cases.json), a manifest of manually
researched expectations each stamped with `evidence_checked_at`. It writes
`.artifacts/scout-source-eval.json` and exits 1 if any case fails. A resolution
slower than `--timeout-seconds` (default 45) is recorded as a failure rather
than a slow pass, so a degraded board cannot quietly report green. Re-verify the
expectations by hand when a case starts failing — the company may simply have
migrated ATS.

## Production health, not synthetic cases

```bash
uv run python scripts/tailor_health.py data/users/<id>/resume_agent.db
```

Opens the DB read-only and reports score distribution, unscored rounds, which
gate blocked each failing round, and the blocking-issue mix. This is the number
that diagnosed the 2026-07-27 scoring bug, and it is the only signal here drawn
from real jobs. Use it to sanity-check that the synthetic corpus is measuring
something the product actually experiences.

## Reading the resume report

Per-case table columns:

| Column | Meaning |
| --- | --- |
| `quality` | Judge's `output_quality`, 0-100 |
| `trap_ok` | No forbidden term from any of the case's traps appears |
| `prov_ok` | Every bullet traces to a real fact id (`check_provenance`) |
| `cite_ok` | Every `must_cite` fact id appears in the output |
| `budget_ok` | Honors hard `max_experiences` / `max_bullets_per_role` |
| `bullets/target` | Actual vs `target_total_bullets` — a target, not a cap |
| `surfaced_round` | Which round the product read-side selector would show |
| `needs_attention` | No round passed the gate cleanly |
| `regressed` | A later round scored worse than an earlier one |
| `portfolio` / `mandatory` / `forbidden` | Evidence-portfolio arm only |

Aggregates worth acting on:

- **Mean output_quality** — comparable only against another run with the same
  judge model and `judge prompt sha256`, both printed under *Run metadata*.
- **Fact-check probe recall** — the fact-check reviewer is run against a
  synthetic probe resume carrying exactly one planted unsupported claim, so an
  unrelated complaint cannot earn credit. Shown as `insufficient data` below
  five completed probes.
- **Reviewer panel_agreement** — Pearson correlation between each advisory
  reviewer's score and the judge's quality on the *same* surfaced draft.
  Requires n>=5 or it reports `insufficient data`. A reviewer whose score does
  not track quality is miscalibrated, and that is the actionable finding.
- **Weakest reviewer** — ranks advisory reviewers (agreement mapped from
  `[-1,1]` onto `[0,1]`) against the fact-check gate's recall on a shared axis,
  so a fully-broken gate is not masked by a mildly anti-correlated reviewer.
  This names the next thing to fix.

The judge is deliberately **profile- and trap-blind**: it sees only the final
resume, the JD, and the rubric. It grades quality, never truthfulness — fact-lock
belongs to the deterministic checks and the in-loop fact-check reviewer. Feeding
it the profile would contaminate `panel_agreement` with leaked ground truth.

## The judge anchor — do this before quoting any absolute number

**Status: not done.** [CALIBRATION.md](CALIBRATION.md) records a Claude
stand-in that had already seen the judge's scores, which does not satisfy the
procedure; and both judge prompts changed on 2026-07-11 (band anchors plus craft
standards), so even those rows belong to a dead prompt hash. Until a human
anchor exists, **only relative arm-to-arm deltas may be claimed.**

To do it:

1. Run the live tier once and keep the timestamped JSON artifact.
2. Pick ~5 cases spanning the range. For each, read the final resume, the JD,
   and the rubric — and nothing else. Stay blind to profile facts, trap labels,
   panel scores, and the judge's own score.
3. Rate `output_quality` 0-100 yourself, against the judge's own bands:
   90-100 ship-ready, 75-89 solid with minor gaps, 60-74 material gaps, below 60
   disqualifying for this job.
4. Record the rows in CALIBRATION.md with date, judge model, prompt sha256, your
   score, the judge's score, and the absolute error.
5. Trust the judge only if **MAE < 10 and no single absolute error exceeds 20**.

Re-run the anchor whenever `judge_prompt_hash()` or the judge model changes.
This is deliberately not automated: an unvalidated judge is the exact disease
the harness exists to cure.

## Running an A/B arm

Change **one** variable. Pin the model, keep both artifacts, and record the
result in RESULTS.md along with the config hash the report prints.

```bash
uv run python -m evals.run_eval --config config/review.yaml.example --model <model> --out evals/reports/<stamp>-baseline.md
```

> **The portfolio A/B described in RESULTS.md is confounded — fix it before
> running.** `config/review.match_plan.yaml` differs from
> `config/review.yaml.example` in far more than the portfolio flag:
>
> | knob | review.yaml.example | review.match_plan.yaml |
> | --- | --- | --- |
> | `evidence_portfolio_enabled` | false | **true** |
> | `max_rounds` | 2 | **3** |
> | `merged_advisory` | true | **false** (default) |
> | `early_stop_on_regression` | true | **false** (default) |
> | `score_bands` | true on all four advisory reviewers | **absent** |
> | `style_guide_path` | `config/style_guide.md` | inherits the default |
>
> Passing the same `--model` to both arms neutralizes the `tailor_tier` /
> `reviser_tier` / per-reviewer tier differences, but not these. A quality delta
> between these two files cannot be attributed to the portfolio planner. Make a
> proper arm instead: copy `review.yaml.example`, flip
> `evidence_portfolio_enabled: true`, change nothing else.

The activation gates the portfolio arm must clear before it ships on by default
are listed at the end of [RESULTS.md](RESULTS.md) — a >=5 point relevance gain,
>=90% mandatory-evidence recall, zero forbidden claims, no provenance /
fact-lock / trap-recall regression, >=7 wins in a blind comparison of ten real
jobs, and acceptable latency and cost.

## Sharp edges

- **`--model` changes pipeline topology, not just the model.** With `--model`
  set, `build_eval_bundle` constructs every advisory reviewer individually and
  never builds the merged advisory agent — so `merged_advisory: true` in the
  config is silently ignored. `make eval` with no `--model` goes through
  `build_tailor_bundle` and *does* honor it. The two invocations therefore
  measure different pipelines; never compare a `--model` run against a bare
  `make eval` run.
- **Merged advisory makes `panel_agreement` less independent.** In merged mode
  the four advisory scores come from one call to one model. They still fan out
  into per-reviewer critiques, so the metric computes — but it is measuring one
  agent's per-dimension calibration, not four independent raters.
- **Small-n metrics silently abstain.** `correlation` needs n>=5 and probe
  recall needs five completed probes; both print `insufficient data` rather than
  a misleading number. A `--limit 3` run has no meta-eval signal at all.
- **Provider cost can be `unknown`.** The metering decorator reports whatever the
  provider returned and never invents a dollar estimate from call count.
- **A round that failed on provenance has no comparable aggregate score.** The
  runtime placeholder is recorded as `None`, not as a quality regression — a
  fabricated `0` was the 2026-07-27 bug.

## Coverage: what has no eval at all

The harness covers the tailor, reviser, reviewer panel, evidence-portfolio
planner, judge, cover-letter writer, and Scout source resolution. Roughly thirty
other `build_*_agent` functions have only faked unit tests and **no quality
measurement**, including:

profile coach · mock interviewer · synthesis and entailment · project extractor ·
taxonomy group classifier · incremental canonicalizer and themer · aspect
classifier · discovery fit and relevance · URL extractor · email writer ·
Career Lab persona and router · bullet dedup.

Extending coverage to one of these means: a hermetic case corpus with
hand-authored expectations; deterministic checks first, since they are
reproducible and free; an LLM judge only for what genuinely cannot be checked
mechanically; and a human anchor before that judge's absolute numbers are quoted
anywhere.

## Adding a resume case

Drop a JSON file in [cases/](cases) matching `EvalCase` in
[schema.py](schema.py): `id`, `profile_ref` (a file in [profiles/](profiles)),
`jd_text`, an optional pre-extracted `criteria`, a non-empty `rubric`, and any
`traps`. Each trap needs a `probe_claim` plus a `probe_provenance` pointing at a
real experience-bullet id in the referenced profile — the harness builds the
recall probe from it and raises if the id does not resolve. `tests/eval` will
reject a malformed case for free, before you spend a cent.
