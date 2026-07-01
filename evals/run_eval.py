import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from evals.judge import build_judge_agent, judge_prompt_hash
from evals.report import render_artifact, render_report
from evals.runner import CaseResult, run_case
from evals.schema import load_cases, load_profile
from resume_agent.discovery.extract import build_extract_agent
from resume_agent.services.agents import TailorBundle, build_tailor_bundle
from resume_agent.tailor.agents import (
    build_reviewer_agent,
    build_reviser_agent,
    build_revision_agent,
    build_tailor_agent,
    model_for_tier,
)
from resume_agent.tailor.match_plan import build_match_plan_agent
from resume_agent.tailor.review_config import ReviewConfig, load_review_config
from resume_agent.tailor.style_guide import load_style_guide


def build_eval_bundle(
    config: ReviewConfig, style_guide: str | None, model_id: str | None
) -> TailorBundle:
    if model_id is None:
        return build_tailor_bundle(config, style_guide=style_guide)
    tailor_agent = build_tailor_agent(model_id, style_guide)
    reviser_agent = build_reviser_agent(model_id, style_guide)
    reviewers = {}
    for spec in config.reviewers:
        reviewers[spec.name] = build_reviewer_agent(
            spec.name,
            model_id,
            style_guide=style_guide,
            score_bands=spec.score_bands,
        )
    revision_agent = build_revision_agent(model_id, style_guide)
    return TailorBundle(
        tailor=tailor_agent,
        reviser=reviser_agent,
        reviewers=reviewers,
        revision=revision_agent,
        match_plan=(
            build_match_plan_agent(model_id, style_guide)
            if config.match_plan_enabled
            else None
        ),
    )


def resolve_config_path(path: Path) -> Path:
    """Fall back to the tracked `.example` config when `path` doesn't exist.

    `config/review.yaml` is gitignored (product setup renders it from the
    example on first run), so a clean checkout has no file at the CLI
    default unless the `.example` fallback kicks in.
    """
    if path.exists():
        return path
    example = path.with_name(path.name + ".example")
    return example if example.exists() else path


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the live resume-quality eval tier."
    )
    parser.add_argument("--cases", default="evals/cases", type=Path)
    parser.add_argument("--profiles", default="evals/profiles", type=Path)
    parser.add_argument("--config", default="config/review.yaml", type=Path)
    parser.add_argument("--out", default=None, type=Path)
    parser.add_argument("--limit", default=None, type=int)
    parser.add_argument("--model", default=None)
    parser.add_argument("--live-criteria", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argparser().parse_args(argv)
    args.config = resolve_config_path(args.config)
    config = load_review_config(args.config)
    cases = load_cases(args.cases)
    if args.limit is not None:
        if args.limit <= 0:
            raise ValueError("--limit must be positive")
        cases = cases[: args.limit]
    if not cases:
        raise ValueError("no eval cases found")

    style_guide = load_style_guide(config.style_guide_path)
    bundle = build_eval_bundle(config, style_guide, args.model)
    judge_agent = build_judge_agent(args.model)
    needs_extract = args.live_criteria or any(case.criteria is None for case in cases)
    extract_agent = build_extract_agent(args.model) if needs_extract else None

    output = args.out or Path("evals/reports") / (
        f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.md"
    )
    artifact_output = output.with_suffix(".json")
    output.parent.mkdir(parents=True, exist_ok=True)
    config_hash = hashlib.sha256(args.config.read_bytes()).hexdigest()
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip() or "unknown"
    effective_models = (
        {"all": args.model}
        if args.model
        else {
            "tailor": model_for_tier("premium"),
            "reviser": model_for_tier("premium"),
            "judge": model_for_tier("premium"),
            "extractor": model_for_tier("cheap") if needs_extract else "not used",
            **{
                f"reviewer:{reviewer.name}": model_for_tier(reviewer.model_tier)
                for reviewer in config.reviewers
            },
        }
    )
    if args.model is None and config.match_plan_enabled:
        effective_models["match-plan"] = model_for_tier("premium")
    metadata = {
        "models": json.dumps(effective_models, sort_keys=True),
        "config sha256": config_hash,
        "style guide sha256": hashlib.sha256(
            (style_guide or "").encode()
        ).hexdigest(),
        "judge prompt sha256": judge_prompt_hash(),
        "git commit": commit,
    }

    results: list[CaseResult] = []
    failures: list[str] = []
    for case in cases:
        try:
            profile = load_profile(case, args.profiles)
            results.append(
                run_case(
                    case,
                    profile,
                    config,
                    bundle,
                    judge_agent,
                    extract_agent=extract_agent,
                    live_criteria=args.live_criteria,
                )
            )
        except Exception as exc:
            failures.append(f"{case.id}: {type(exc).__name__}: {exc}")
            if args.fail_fast:
                break
        finally:
            output.write_text(
                render_report(
                    results,
                    config,
                    metadata=metadata,
                    failures=failures,
                ),
                encoding="utf-8",
            )
            artifact_output.write_text(
                render_artifact(
                    results,
                    metadata=metadata,
                    failures=failures,
                ),
                encoding="utf-8",
            )

    report = render_report(
        results, config, metadata=metadata, failures=failures
    )
    print(report)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
