# UCCM controlled switch

The only behavior switch remains `CAREER_CAPABILITY_MODE=legacy|shadow|uccm`.

- `legacy` skips graph construction and uses the legacy taxonomy and matcher.
- `shadow` builds Match Engine v2 artifacts while legacy behavior remains primary.
- `uccm` requests UCCM-primary behavior, but activates it only when `UCCM_EVALUATION_REPORT_PATH` (default `data/evals/uccm_activation_report.json`) contains a complete, reviewed, current, sealed report for the exact taxonomy, assertion, extraction, and matching-policy revisions.

Missing, unreadable, unreviewed, unsigned, expired, tampered, incomplete, ineligible, threshold-failing, or revision-mismatched reports fall back to effective `shadow` mode. The manifest records `capability_mode=uccm`, `capability_effective_mode=shadow`, `capability_status=fallback`, and a stable `capability_error_code`.

Offline evaluation tooling can call `evals.uccm.build_activation_report(...)` to produce the sealed runtime artifact. The bundled gold fixture is unreviewed and therefore cannot produce a production-eligible activation report.

Rollback requires only changing `CAREER_CAPABILITY_MODE` to `shadow` or `legacy` and restarting the process. No stored profile, job, match, or resume-version artifact is rewritten or deleted. Legacy demand, coverage, and tailoring adapters remain available for the compatibility window; removal requires a separate deprecation decision.
