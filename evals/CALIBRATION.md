# Judge Calibration

The live eval judge (`evals/judge.py`) is trusted only after a one-time human anchor.

## Procedure

1. Run `make eval` once with a real API key and retain its timestamped JSON artifact.
2. Pick ~5 cases from that artifact. For each, read the final resume, JD, and rubric and rate `output_quality` 0–100 (blind to profile facts, traps, panel scores, and the judge's score).
3. Record below. Trust the judge only if MAE < 10 and no individual absolute error exceeds 20.
4. Re-run this anchor whenever the judge prompt or model changes.

## Record

| date | judge model | prompt sha256 | case | human | judge | abs error |
| --- | --- | --- | --- | --- | --- | --- |
| _TBD_ | | | | | | |

**MAE:** _TBD_ · **Trusted:** _no (not yet anchored)_
