from resume_agent.models.evidence_portfolio import (
    EvidencePortfolio,
    PortfolioOmission,
    PortfolioRequirement,
    PortfolioSelection,
)
from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import (
    Bullet,
    Contact,
    Experience,
    ProfileFacts,
    Project,
    Skill,
)
from resume_agent.models.resume import (
    ResumeContent,
    TailoredBullet,
    TailoredExperience,
    TailoredSkill,
)
from resume_agent.profile.matrix import MatrixRow, SkillMatch, SkillMatchContext
from resume_agent.tailor.evidence_portfolio import (
    build_evidence_catalog,
    build_fallback_portfolio,
    normalize_evidence_portfolio,
    portfolio_profile,
)
from resume_agent.tailor.portfolio_alignment import portfolio_alignment_critique
from resume_agent.tailor.review_config import LengthBudget


def _facts() -> ProfileFacts:
    return ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[
            Experience(
                id="exp-recent",
                company="RetailCo",
                title="Analyst",
                start="2024",
                current=True,
                bullets=[Bullet(id="retail", text="Prepared weekly inventory reports")],
            ),
            Experience(
                id="exp-api",
                company="ScaleCo",
                title="Engineer",
                start="2021",
                end="2023",
                bullets=[
                    Bullet(
                        id="api",
                        text="Built Python APIs and reduced p95 latency from 500ms to 200ms",
                    ),
                    Bullet(id="docs", text="Documented service runbooks"),
                ],
            ),
        ],
        projects=[
            Project(
                id="project-kafka",
                name="Event platform",
                description="Python event processing service",
                tech=["Python", "Kafka"],
                highlights=["Processed 2M events per day"],
                last_updated="2025-01-01",
            )
        ],
        skills={
            "Languages": [Skill(id="skill-python", name="Python", aliases=["Python 3"])],
            "Messaging": [Skill(id="skill-kafka", name="Apache Kafka", aliases=["Kafka"])],
            "Cloud": [Skill(id="skill-aws", name="Amazon Web Services", aliases=["AWS"])],
        },
    )


def _context() -> SkillMatchContext:
    return SkillMatchContext(
        matches=[
            SkillMatch(
                requirement="Python",
                source="must",
                coverage="covered",
                row=MatrixRow(
                    key="python",
                    display="Python",
                    evidence_fact_ids=["skill-python", "api", "project-kafka"],
                    strength=2.0,
                    last_used="current",
                ),
            ),
            SkillMatch(
                requirement="Kafka",
                source="must",
                coverage="covered",
                row=MatrixRow(
                    key="kafka",
                    display="Apache Kafka",
                    aliases=["Kafka"],
                    evidence_fact_ids=["skill-kafka", "project-kafka"],
                    strength=1.0,
                    last_used="2025",
                ),
            ),
            SkillMatch(
                requirement="Kubernetes",
                source="must",
                coverage="adjacent",
                row=MatrixRow(
                    key="aws",
                    display="Amazon Web Services",
                    evidence_fact_ids=["skill-aws"],
                ),
            ),
        ]
    )


def _criteria() -> JobCriteria:
    return JobCriteria(must_have_skills=["Python", "Kafka", "Kubernetes"])


def test_catalog_links_job_skills_to_exact_owners_and_metric_facts():
    catalog = build_evidence_catalog(_facts(), _criteria(), _context())

    api = next(owner for owner in catalog.owners if owner.owner_id == "exp-api")
    project = next(owner for owner in catalog.owners if owner.owner_id == "project-kafka")

    assert api.direct_requirements == ["Python"]
    assert api.facts[0].metric_count == 2
    assert api.facts[0].direct_requirements == ["Python"]
    assert project.direct_requirements == ["Python", "Kafka"]
    assert project.owner_kind == "project"


def test_fallback_lets_a_strong_project_beat_an_unrelated_recent_role():
    budget = LengthBudget(
        max_experiences=1,
        max_projects=1,
        max_evidence_owners=2,
        max_bullets_per_role=2,
        max_bullets_per_project=2,
        target_total_bullets=3,
    )
    catalog = build_evidence_catalog(_facts(), _criteria(), _context())

    portfolio = build_fallback_portfolio(
        catalog, _facts(), _criteria(), _context(), budget, warning="planner failed"
    )

    selected = [selection.owner_id for selection in portfolio.selections]
    assert selected == ["project-kafka", "exp-api"]
    assert "exp-recent" not in selected
    assert portfolio.status == "deterministic_fallback"
    assert portfolio.highlight_terms == ["Python", "Kafka"]


def test_normalization_rejects_bad_ids_gap_terms_and_budget_overflow():
    draft = EvidencePortfolio(
        status="planned",
        requirements=[
            PortfolioRequirement(
                text="Kubernetes",
                kind="skill",
                priority=1,
                coverage="covered",
                supporting_fact_ids=["ghost"],
                approved_terms=["Kubernetes"],
                core=True,
            ),
            PortfolioRequirement(
                text="Python",
                kind="skill",
                priority=2,
                coverage="gap",
                supporting_fact_ids=["api", "ghost"],
                approved_terms=["Python", "Python 3"],
                core=True,
            ),
        ],
        selections=[
            PortfolioSelection(
                owner_id="exp-api",
                owner_kind="experience",
                selected_fact_ids=["api", "retail", "ghost"],
                requirement_texts=["Python", "Kubernetes"],
                rank=1,
                bullet_budget=99,
                rationale="best API evidence",
            ),
            PortfolioSelection(
                owner_id="ghost-owner",
                owner_kind="project",
                selected_fact_ids=["ghost"],
                rank=2,
                bullet_budget=3,
            ),
        ],
        selected_skill_fact_ids=["skill-python", "skill-aws", "ghost"],
        highlight_terms=["Kubernetes", "Python 3", "ghost"],
        omissions=[
            PortfolioOmission(
                owner_id="exp-recent",
                owner_kind="experience",
                rationale="less relevant",
            )
        ],
    )
    budget = LengthBudget(max_bullets_per_role=2, target_total_bullets=2)
    catalog = build_evidence_catalog(_facts(), _criteria(), _context())

    normalized = normalize_evidence_portfolio(
        draft, catalog, _facts(), _criteria(), _context(), budget
    )

    selection = normalized.selections[0]
    assert selection.selected_fact_ids == ["api"]
    assert selection.bullet_budget == 1
    assert [requirement.text for requirement in normalized.requirements[:3]] == [
        "Python",
        "Kafka",
        "Kubernetes",
    ]
    assert normalized.requirements[0].coverage == "covered"
    assert normalized.requirements[2].coverage == "adjacent"
    assert normalized.highlight_terms == ["Python", "Kafka"]
    assert normalized.selected_skill_fact_ids == ["skill-python", "skill-kafka"]
    assert "ghost" not in normalized.model_dump_json()


def test_portfolio_profile_keeps_only_approved_work_project_and_skills():
    catalog = build_evidence_catalog(_facts(), _criteria(), _context())
    portfolio = build_fallback_portfolio(
        catalog,
        _facts(),
        _criteria(),
        _context(),
        LengthBudget(max_experiences=1, max_evidence_owners=2),
    )

    sliced = portfolio_profile(_facts(), portfolio)

    assert [experience.id for experience in sliced.experience] == ["exp-api"]
    assert [bullet.id for bullet in sliced.experience[0].bullets] == ["api"]
    assert [project.id for project in sliced.projects] == ["project-kafka"]
    assert {
        skill.id for entries in sliced.skills.values() for skill in entries
    } == {"skill-python", "skill-kafka"}
    assert sliced.contact == _facts().contact


def test_alignment_requires_core_skill_in_list_and_context_when_available():
    catalog = build_evidence_catalog(_facts(), _criteria(), _context())
    portfolio = build_fallback_portfolio(
        catalog, _facts(), _criteria(), _context(), LengthBudget()
    )
    content = ResumeContent(
        contact=Contact(name="Ada"),
        experience=[
            TailoredExperience(
                company="ScaleCo",
                title="Engineer",
                provenance="exp-api",
                bullets=[TailoredBullet(text="Improved API latency", provenance="api")],
            )
        ],
        skills={
            "Languages": [TailoredSkill(name="Python", provenance="skill-python")]
        },
    )

    critique = portfolio_alignment_critique(content, portfolio)

    assert critique.passed is True
    assert critique.score == 25
    messages = [issue.message for issue in critique.issues]
    assert any("Python" in message and "context" in message for message in messages)
    assert any("Kafka" in message and "skills section" in message for message in messages)
