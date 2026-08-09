import json
from statistics import mean

from pydantic import TypeAdapter

from evals.metrics import (
    RoundRecord,
    convergence,
    correlation,
    fact_check_trap_recall,
    total_bullets,
)
from evals.runner import CaseResult
from resume_agent.tailor.review_config import ReviewConfig


def _surfaced_record(result: CaseResult) -> RoundRecord:
    if result.surfaced_round_num is None:
        return result.rounds[-1]
    for round_ in result.rounds:
        if round_.round_num == result.surfaced_round_num:
            return round_
    raise ValueError(
        f"case {result.case_id!r} surfaced unknown round {result.surfaced_round_num}"
    )


def _reviewer_score(result: CaseResult, name: str) -> int | None:
    if not result.rounds:
        return None
    return next(
        (
            critique.score
            for critique in _surfaced_record(result).critiques
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
        "bullets/target | rounds | surfaced_round | needs_attention | regressed | "
        "portfolio | mandatory | forbidden | calls | total_tokens | cost |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | "
        "--- | --- | --- | --- | --- | --- |",
    ]
    for result in results:
        rounds_used, _ = convergence(result.rounds)
        surfaced = _surfaced_record(result)
        cost = "unknown" if result.usage.cost is None else f"${result.usage.cost:.4f}"
        lines.append(
            f"| {result.case_id} | {result.final_quality} | "
            f"{result.trap_avoided} | {result.provenance_ok} | "
            f"{result.must_cite_covered} | {result.budget_ok} | "
            f"{total_bullets(surfaced.content)}/"
            f"{config.length_budget.target_total_bullets} | "
            f"{rounds_used} | {result.surfaced_round_num} | "
            f"{result.needs_attention} | {result.regressed} | "
            f"{result.portfolio_status or 'off'} | "
            f"{result.portfolio_mandatory_hits}/{result.portfolio_mandatory_total} | "
            f"{len(result.portfolio_forbidden_hits)} | "
            f"{result.usage.calls} | "
            f"{result.usage.total_tokens} | {cost} |"
        )

    mean_quality = (
        round(mean(result.final_quality for result in results)) if results else 0
    )
    total_tokens = sum(result.usage.total_tokens for result in results)
    cache_read_tokens = sum(result.usage.cache_read_tokens for result in results)
    cache_write_tokens = sum(result.usage.cache_write_tokens for result in results)
    known_cost = sum(result.usage.cost or 0.0 for result in results)
    unknown_costs = sum(result.usage.cost is None for result in results)
    mandatory_hits = sum(result.portfolio_mandatory_hits for result in results)
    mandatory_total = sum(result.portfolio_mandatory_total for result in results)
    forbidden_hits = sum(len(result.portfolio_forbidden_hits) for result in results)
    portfolio_results = [
        result for result in results if result.portfolio_status is not None
    ]
    fallback_count = sum(
        result.portfolio_status == "deterministic_fallback"
        for result in portfolio_results
    )
    elapsed_seconds = sum(
        sum((round_.phase_seconds or {}).values())
        for result in results
        for round_ in result.rounds
    )
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
        f"**Cache read tokens:** {cache_read_tokens}",
        f"**Cache write tokens:** {cache_write_tokens}",
        f"**Known provider cost:** ${known_cost:.4f} ({unknown_costs} unknown case(s))",
        f"**Portfolio mandatory-evidence recall:** "
        f"{mandatory_hits / mandatory_total:.2%} ({mandatory_hits}/{mandatory_total})"
        if mandatory_total
        else "**Portfolio mandatory-evidence recall:** not labeled",
        f"**Portfolio forbidden claims/highlights:** {forbidden_hits}",
        f"**Portfolio fallback rate:** "
        f"{fallback_count / len(portfolio_results):.2%} ({fallback_count}/{len(portfolio_results)})"
        if portfolio_results
        else "**Portfolio fallback rate:** feature off",
        f"**Measured tailoring latency:** {elapsed_seconds:.2f}s",
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

    # panel_agreement is a Pearson correlation in [-1, 1]; the gate's recall is
    # in [0, 1]. Rank both on a shared 0..1 "usefulness" axis so a fully-broken
    # gate (recall 0) is not masked by a mildly anti-correlated panel reviewer.
    ranked = [
        (reviewer_name, (agreement + 1.0) / 2.0)
        for reviewer_name, agreement in agreements.items()
        if agreement is not None
    ]
    if recall_rankable:
        assert recall is not None
        ranked.append(("fact-check", recall))
    weakest = (
        min(ranked, key=lambda item: item[1])[0] if ranked else "insufficient data"
    )
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
