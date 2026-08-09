from pathlib import Path

from evals.metrics import portfolio_forbidden_hits, portfolio_mandatory_hits
from evals.schema import load_cases, load_profile
from resume_agent.profile.matrix import Overrides, build_matrix, build_skill_match_context
from resume_agent.tailor.evidence_portfolio import (
    build_evidence_catalog,
    build_fallback_portfolio,
)
from resume_agent.tailor.review_config import LengthBudget
from resume_agent.taxonomy.clusters import load_cluster_map


def test_labeled_portfolio_cases_meet_deterministic_safety_floor():
    cases = [
        case
        for case in load_cases(Path("evals/cases"))
        if case.portfolio_expectation is not None
    ]
    assert {case.portfolio_expectation.label for case in cases} == {
        "competing_roles",
        "stronger_projects",
        "career_change",
        "overlong_profile",
        "direct_vs_adjacent",
        "safe_alias",
    }

    cluster_map = load_cluster_map(Path("evals/portfolio_cluster_map.json"))
    hits = 0
    total = 0
    forbidden: list[str] = []
    for case in cases:
        assert case.criteria is not None
        expectation = case.portfolio_expectation
        assert expectation is not None
        profile = load_profile(case, Path("evals/profiles"))
        matrix = build_matrix(profile, cluster_map, Overrides())
        context = build_skill_match_context(case.criteria, matrix, cluster_map)
        catalog = build_evidence_catalog(profile, case.criteria, context)
        portfolio = build_fallback_portfolio(
            catalog,
            profile,
            case.criteria,
            context,
            LengthBudget(),
        )
        case_hits, case_total = portfolio_mandatory_hits(
            portfolio, expectation.mandatory_evidence_ids
        )
        hits += case_hits
        total += case_total
        forbidden.extend(
            portfolio_forbidden_hits(
                portfolio,
                expectation.forbidden_evidence_ids,
                expectation.forbidden_highlight_terms,
            )
        )

    assert hits / total >= 0.90
    assert forbidden == []
