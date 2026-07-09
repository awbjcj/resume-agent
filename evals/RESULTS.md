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
