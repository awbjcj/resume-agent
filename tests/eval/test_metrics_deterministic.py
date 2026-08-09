from evals.metrics import (
    budget_ok,
    must_cite_covered,
    portfolio_forbidden_hits,
    portfolio_mandatory_hits,
    provenance_ok,
    total_bullets,
    trap_avoided,
)
from evals.schema import Trap
from resume_agent.models.profile import Bullet, Contact, Experience, ProfileFacts
from resume_agent.models.evidence_portfolio import (
    EvidencePortfolio,
    PortfolioSelection,
)
from resume_agent.models.resume import ResumeContent, TailoredBullet, TailoredExperience
from resume_agent.tailor.review_config import LengthBudget


def _facts() -> ProfileFacts:
    return ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[
            Experience(
                id="e1",
                company="AE",
                title="Eng",
                bullets=[Bullet(id="b1", text="Built API")],
            )
        ],
    )


def _resume(
    provenance: str = "e1",
    bullet_prov: str = "b1",
    bullet_text: str = "Built API",
) -> ResumeContent:
    return ResumeContent(
        contact=Contact(name="Ada"),
        experience=[
            TailoredExperience(
                company="AE",
                title="Eng",
                provenance=provenance,
                bullets=[TailoredBullet(text=bullet_text, provenance=bullet_prov)],
            )
        ],
    )


def _trap(term: str) -> Trap:
    return Trap(
        id="trap",
        kind="missing_skill",
        forbidden_terms=[term],
        description="x",
        probe_claim=f"Built {term}",
        probe_provenance="b1",
    )


def test_trap_avoided_true_when_clean():
    assert trap_avoided(_resume(), [_trap("Kubernetes")]) is True


def test_trap_avoided_false_when_term_present():
    assert trap_avoided(_resume(bullet_text="Built API"), [_trap("API")]) is False


def test_provenance_ok_true_for_valid_ids():
    assert provenance_ok(_resume(), _facts()) is True


def test_provenance_ok_false_for_ghost_id():
    assert provenance_ok(_resume(bullet_prov="ghost"), _facts()) is False


def test_must_cite_covered():
    assert must_cite_covered(_resume(), ["e1", "b1"]) is True
    assert must_cite_covered(_resume(), ["e1", "missing"]) is False


def test_budget_ok():
    tight = LengthBudget(
        max_experiences=1,
        max_bullets_per_role=1,
        target_total_bullets=1,
    )
    overflow = LengthBudget(
        max_experiences=1,
        max_bullets_per_role=0,
        target_total_bullets=0,
    )
    target_is_not_a_hard_cap = LengthBudget(
        max_experiences=1,
        max_bullets_per_role=1,
        target_total_bullets=0,
    )

    assert budget_ok(_resume(), tight) is True
    assert budget_ok(_resume(), overflow) is False
    assert budget_ok(_resume(), target_is_not_a_hard_cap) is True


def test_total_bullets_counts_resume_bullets():
    assert total_bullets(_resume()) == 1


def test_portfolio_expectation_metrics_count_required_and_forbidden_selection():
    portfolio = EvidencePortfolio(
        highlight_terms=["Python", "Flask"],
        selections=[
            PortfolioSelection(
                owner_id="e1",
                owner_kind="experience",
                selected_fact_ids=["b1"],
            )
        ],
    )

    assert portfolio_mandatory_hits(portfolio, ["e1", "b1", "missing"]) == (2, 3)
    assert portfolio_forbidden_hits(
        portfolio, ["b1", "ghost"], ["flask", "Kubernetes"]
    ) == ["b1", "highlight:flask"]
