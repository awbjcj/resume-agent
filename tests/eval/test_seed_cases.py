from pathlib import Path

from evals.schema import load_cases, load_profile
from evals.textscan import term_present
from resume_agent.models.profile import Bullet
from resume_agent.tailor.provenance import index_facts

CASES = Path("evals/cases")
PROFILES = Path("evals/profiles")


def test_at_least_eight_seed_cases():
    cases = load_cases(CASES)

    assert len(cases) >= 8
    assert len({case.id for case in cases}) == len(cases)


def test_each_case_valid_and_grounded():
    for case in load_cases(CASES):
        profile = load_profile(case, PROFILES)
        facts_by_id = index_facts(profile)
        valid_ids = set(facts_by_id)
        for fact_id in case.must_cite:
            assert fact_id in valid_ids, (
                f"{case.id}: must_cite {fact_id} not in profile"
            )
        assert case.traps, f"{case.id}: an adversarial case needs at least one trap"
        for trap in case.traps:
            assert trap.forbidden_terms, f"{case.id}: trap has no forbidden_terms"
            assert trap.probe_provenance in facts_by_id
            assert isinstance(facts_by_id[trap.probe_provenance], Bullet)
            assert any(
                term_present(trap.probe_claim, term)
                for term in trap.forbidden_terms
            )
        assert case.rubric, f"{case.id}: needs judge rubric dimensions"


def test_trap_kinds_cover_all_four():
    kinds = {trap.kind for case in load_cases(CASES) for trap in case.traps}

    assert {
        "missing_skill",
        "adjacent_skill",
        "inflatable_metric",
        "seniority_inflation",
    } <= kinds
