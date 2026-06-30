import json
from statistics import mean

from pydantic import TypeAdapter

from evals.metrics import (
    convergence,
    correlation,
    fact_check_trap_recall,
    total_bullets,
)
from evals.runner import CaseResult
from resume_agent.tailor.review_config import ReviewConfig


def _reviewer_score(result: CaseResult, name: str) -> int | None:
    if not result.rounds:
        return None
    return next(
        (
            critique.score
            for critique in result.rounds[-1].critiques
            if critique.reviewer == name
        ),
        None,
    )


def render_report(
    results: list[CaseResult],
    config: ReviewConfig,
    *,
    metadata: dict[str, str] | None = None,
    failures: list[str] | None = None,
) -> str:
    lines: list[str] = [
        "# Eval Report",
        "",
        "## Per-case",
        "",
        "| case | quality | trap_ok | prov_ok | cite_ok | budget_ok | "
        "bullets/target | rounds | regressed | calls | total_tokens | cost |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | "
        "--- | --- |",
    ]
    for result in results:
        rounds_used, regressed = convergence(result.rounds)
        cost = (
            "unknown"
            if result.usage.cost is None
            else f"${result.usage.cost:.4f}"
        )
        lines.append(
            f"| {result.case_id} | {result.final_quality} | "
            f"{result.trap_avoided} | {result.provenance_ok} | "
            f"{result.must_cite_covered} | {result.budget_ok} | "
            f"{total_bullets(result.rounds[-1].content)}/"
            f"{config.length_budget.target_total_bullets} | "
            f"{rounds_used} | {regressed} | {result.usage.calls} | "
            f"{result.usage.total_tokens} | {cost} |"
        )

    mean_quality = round(mean(result.final_quality for result in results)) if results else 0
    total_tokens = sum(result.usage.total_tokens for result in results)
    known_cost = sum(result.usage.cost or 0.0 for result in results)
    unknown_costs = sum(result.usage.cost is None for result in results)
    probes = [probe for result in results for probe in result.probes]
    completed_probes = [probe for probe in probes if probe.detected is not None]
    recall = fact_check_trap_recall(probes)
    recall_rankable = recall is not None and len(completed_probes) >= 5
    shown_recall = f"{recall:.2f}" if recall_rankable else "insufficient data"
    lines += [
        "",
        f"**Mean output_quality:** {mean_quality}",
        f"**Fact-check probe recall:** {shown_recall}",
        f"**Fact-check probe coverage:** {len(completed_probes)}/{len(probes)}",
        f"**Total tokens:** {total_tokens}",
        f"**Known provider cost:** ${known_cost:.4f} "
        f"({unknown_costs} unknown case(s))",
        "",
        "## Reviewer panel_agreement",
        "",
    ]

    agreements: dict[str, float | None] = {}
    for spec in config.reviewers:
        if spec.gate:
            continue
        reviewer_scores: list[float] = []
        quality_scores: list[float] = []
        for result in results:
            score = _reviewer_score(result, spec.name)
            if score is not None:
                reviewer_scores.append(float(score))
                quality_scores.append(float(result.final_quality))
        agreement = correlation(reviewer_scores, quality_scores)
        agreements[spec.name] = agreement
        shown = (
            f"insufficient data (n={len(reviewer_scores)})"
            if agreement is None
            else f"{agreement:.2f} (n={len(reviewer_scores)})"
        )
        lines.append(f"- {spec.name}: panel_agreement = {shown}")

    ranked = [
        (reviewer_name, agreement)
        for reviewer_name, agreement in agreements.items()
        if agreement is not None
    ]
    if recall_rankable:
        assert recall is not None
        ranked.append(("fact-check", recall))
    weakest = min(ranked, key=lambda item: item[1])[0] if ranked else "insufficient data"
    lines += ["", f"**Weakest reviewer:** {weakest}", ""]
    if metadata:
        lines += [
            "## Run metadata",
            *[f"- {key}: {value}" for key, value in metadata.items()],
            "",
        ]
    if failures:
        lines += ["## Failures", *[f"- {failure}" for failure in failures], ""]
    return "\n".join(lines)


def render_artifact(
    results: list[CaseResult], *, metadata: dict[str, str], failures: list[str]
) -> str:
    payload = {
        "metadata": metadata,
        "failures": failures,
        "results": TypeAdapter(list[CaseResult]).dump_python(results, mode="json"),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)
