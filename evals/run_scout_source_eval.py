"""Run the opt-in, read-only Discovery Scout ATS source evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

# Keep the documented ``python evals/run_scout_source_eval.py`` invocation
# working as well as ``python -m evals.run_scout_source_eval``. Python otherwise
# places only the ``evals`` directory on sys.path for the direct-script form.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.scout_source_eval import (
    ScoutSourceEvalResult,
    load_source_cases,
    run_source_case,
)
from resume_tailor_harness.discovery.source_resolution.resolver import CompanySourceResolver
from resume_tailor_harness.tenancy.paths import SEARCH_PATH


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run live, read-only checks for Scout ATS board accuracy."
    )
    parser.add_argument(
        "--cases", type=Path, default=Path("evals/scout_source_cases.json")
    )
    parser.add_argument(
        "--output", type=Path, default=Path(".artifacts/scout-source-eval.json")
    )
    parser.add_argument("--search-path", default=SEARCH_PATH)
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    return parser


def _with_time_budget(
    result: ScoutSourceEvalResult, timeout_seconds: float
) -> ScoutSourceEvalResult:
    """Never report a slow board as a successful live check.

    The production resolver owns its request and company deadlines. This guard
    preserves those bounded calls while making an evaluator-specific overrun a
    visible failure in the written report.
    """

    if result.elapsed_seconds <= timeout_seconds:
        return result
    return result.model_copy(
        update={
            "passed": False,
            "error": result.error
            or f"TIME_BUDGET_EXCEEDED: {result.elapsed_seconds:.1f}s > {timeout_seconds:.1f}s",
        }
    )


def _report_payload(
    results: list[ScoutSourceEvalResult],
    *,
    cases_path: Path,
    timeout_seconds: float,
) -> dict:
    return {
        "metadata": {
            "generatedAt": datetime.now(UTC).isoformat(),
            "cases": str(cases_path),
            "timeoutSeconds": timeout_seconds,
        },
        "results": [result.model_dump(mode="json") for result in results],
        "summary": {
            "total": len(results),
            "passed": sum(result.passed for result in results),
            "failed": sum(not result.passed for result in results),
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = build_argparser().parse_args(argv)
    if args.timeout_seconds <= 0:
        raise ValueError("--timeout-seconds must be positive")
    cases = load_source_cases(args.cases)
    if not cases:
        raise ValueError("no Scout source cases found")

    resolver = CompanySourceResolver(args.search_path)
    results = [
        _with_time_budget(
            run_source_case(case, resolver),
            args.timeout_seconds,
        )
        for case in cases
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            _report_payload(
                results,
                cases_path=args.cases,
                timeout_seconds=args.timeout_seconds,
            ),
            indent=2,
        ),
        encoding="utf-8",
    )
    for result in results:
        verdict = "PASS" if result.passed else "FAIL"
        print(
            f"{verdict} {result.company}: expected={result.expected_ats} "
            f"actual={result.actual_ats or '-'} status={result.status} "
            f"url={result.actual_board_url or '-'}"
        )
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
