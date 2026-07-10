# Eval Results Log

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
