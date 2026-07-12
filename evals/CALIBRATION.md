# Judge Calibration

The live eval judge (`evals/judge.py`) is trusted only after a one-time human anchor.

## Procedure

1. Run `make eval` once with a real API key and retain its timestamped JSON artifact.
2. Pick ~5 cases from that artifact. For each, read the final resume, JD, and rubric and rate `output_quality` 0–100 (blind to profile facts, traps, panel scores, and the judge's score).
3. Record below. Trust the judge only if MAE < 10 and no individual absolute error exceeds 20.
4. Re-run this anchor whenever the judge prompt or model changes.

## Record

> **Note:** the rows below are a Claude stand-in rating, not a human anchor. Claude
> read each blinded packet (final resume + JD + rubric, no scores/facts/traps) and
> scored `output_quality` itself instead of a person doing it, and did so already
> aware of the judge's scores from the run report — so this does not satisfy the
> procedure above and must not be used to mark the judge trusted. Re-run this
> anchor with an actual human rater before relying on `evals/judge.py` output.

| date | judge model | prompt sha256 | case | human (stand-in: Claude) | judge | abs error |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-07-08 | deepseek:deepseek-v4-pro | 64ed837a3ed9c1809441f026ed6581623a7697fd92fc2ed14b5db733c34ce8bd | case_04_seniority_inflation | 15 | 10 | 5 |
| 2026-07-08 | deepseek:deepseek-v4-pro | 64ed837a3ed9c1809441f026ed6581623a7697fd92fc2ed14b5db733c34ce8bd | case_01_missing_skill | 20 | 20 | 0 |
| 2026-07-08 | deepseek:deepseek-v4-pro | 64ed837a3ed9c1809441f026ed6581623a7697fd92fc2ed14b5db733c34ce8bd | case_03_inflatable_metric | 35 | 35 | 0 |
| 2026-07-08 | deepseek:deepseek-v4-pro | 64ed837a3ed9c1809441f026ed6581623a7697fd92fc2ed14b5db733c34ce8bd | case_09_metric_rich | 85 | 90 | 5 |
| 2026-07-08 | deepseek:deepseek-v4-pro | 64ed837a3ed9c1809441f026ed6581623a7697fd92fc2ed14b5db733c34ce8bd | case_10_keyword_mismatch | 90 | 97 | 7 |

**MAE (stand-in):** 3.4 · **Trusted:** _no (stand-in only — needs a real human anchor per the procedure above)_

> **2026-07-11:** both judge prompts gained band anchors (90/75/60 quality
> bands) and explicit resume/cover-letter craft standards distilled from
> resume-writing playbooks, so `judge_prompt_hash()` and
> `cl_judge_prompt_hash()` changed. The rows above belong to the previous
> prompt hash; the anchor procedure must be re-run against the new prompts.
