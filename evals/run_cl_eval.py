import argparse
import hashlib
import json
import subprocess
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from evals.cl_runner import CLCaseResult, run_cl_case
from evals.judge import build_cl_judge_agent, cl_judge_prompt_hash
from evals.schema import load_cases, load_profile
from resume_agent.cover_letter.agents import (
    build_cover_letter_agent,
    build_cover_letter_reviser_agent,
)
from resume_agent.tailor.agents import model_for_tier
from resume_agent.tailor.style_guide import load_style_guide


def result_dict(result: CLCaseResult) -> dict:
    return {
        "caseId": result.case_id,
        "reviseRounds": result.revise_rounds,
        "trapOk": result.trap_ok,
        "provenanceOk": result.provenance_ok,
        "finalQuality": result.final_quality,
        "judge": result.judge.model_dump(mode="json"),
        "letter": result.letter.model_dump(mode="json"),
        "usage": asdict(result.usage),
    }


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the live cover-letter eval tier (measure-only)."
    )
    parser.add_argument("--cases", default="evals/cases", type=Path)
    parser.add_argument("--profiles", default="evals/profiles", type=Path)
    parser.add_argument("--out", default=None, type=Path)
    parser.add_argument("--limit", default=None, type=int)
    parser.add_argument("--model", default=None)
    parser.add_argument(
        "--style-guide",
        default="config/style_guide.md",
        type=Path,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argparser().parse_args(argv)
    cases = [case for case in load_cases(args.cases) if case.target == "cover_letter"]
    if args.limit is not None:
        if args.limit <= 0:
            raise ValueError("--limit must be positive")
        cases = cases[: args.limit]
    if not cases:
        raise ValueError("no cover-letter eval cases found")

    draft_agent = build_cover_letter_agent(args.model)
    reviser_agent = build_cover_letter_reviser_agent(args.model)
    judge_agent = build_cl_judge_agent(args.model)
    style_guide = load_style_guide(args.style_guide)

    output = args.out or Path("evals/reports") / (
        f"cl-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    commit = (
        subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        or "unknown"
    )
    metadata = {
        "models": json.dumps(
            (
                {"all": args.model}
                if args.model
                else {
                    "draft": model_for_tier("premium"),
                    "reviser": model_for_tier("mid"),
                    "judge": model_for_tier("premium"),
                }
            ),
            sort_keys=True,
        ),
        "cl judge prompt sha256": cl_judge_prompt_hash(),
        "style guide sha256": hashlib.sha256((style_guide or "").encode()).hexdigest(),
        "git commit": commit,
    }

    results: list[CLCaseResult] = []
    failures: list[str] = []
    for case in cases:
        try:
            profile = load_profile(case, args.profiles)
            results.append(
                run_cl_case(
                    case,
                    profile,
                    draft_agent,
                    reviser_agent,
                    judge_agent,
                    style_guide=style_guide,
                )
            )
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{case.id}: {type(exc).__name__}: {exc}")
        finally:
            output.write_text(
                json.dumps(
                    {
                        "metadata": metadata,
                        "results": [result_dict(result) for result in results],
                        "failures": failures,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

    for result in results:
        print(
            f"{result.case_id}: quality={result.final_quality} "
            f"trap_ok={result.trap_ok} "
            f"provenance_ok={result.provenance_ok} "
            f"revise_rounds={result.revise_rounds}"
        )
    if results:
        mean_quality = sum(result.final_quality for result in results) / len(results)
        print(
            f"mean quality: {mean_quality:.1f} over "
            f"{len(results)} case(s); failures: {len(failures)}"
        )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
