from resume_agent.models.profile import Bullet, Contact, Experience, ProfileFacts, Project
from resume_agent.models.resume import (
    ResumeContent,
    TailoredBullet,
    TailoredExperience,
    TailoredProject,
)
from resume_agent.models.review import Severity
from resume_agent.profile.aspects import Aspect
from resume_agent.tailor.depth import DEPTH_REVIEWER, depth_critique
from resume_agent.tailor.review_config import LengthBudget


def _facts(*, repeated_aspect: bool = False) -> ProfileFacts:
    aspects: list[Aspect] = ["technical"] * 6 if repeated_aspect else [
        "scope",
        "technical",
        "impact",
        "collaboration",
        "leadership",
        "process",
    ]
    return ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[
            Experience(
                id="exp-rich",
                company="Acme",
                title="Engineer",
                bullets=[
                    Bullet(id=f"rich-{index}", text=f"Rich {index}", aspect=aspect)
                    for index, aspect in enumerate(aspects)
                ],
            ),
            Experience(
                id="exp-thin",
                company="Beta",
                title="Engineer",
                bullets=[Bullet(id=f"thin-{index}", text=f"Thin {index}") for index in range(2)],
            ),
            Experience(
                id="exp-excluded",
                company="Gamma",
                title="Engineer",
                bullets=[Bullet(id=f"excluded-{index}", text=f"Excluded {index}") for index in range(6)],
            ),
        ],
        projects=[
            Project(
                id="prj-one",
                name="Project one",
                highlights=[
                    Bullet(id=f"project-{index}", text=f"Project {index}", aspect="technical")
                    for index in range(4)
                ],
            )
        ],
    )


def _resume(*, rich: int = 5, thin: int = 2, project: int = 4) -> ResumeContent:
    return ResumeContent(
        contact=Contact(name="Ada"),
        experience=[
            TailoredExperience(
                company="Acme",
                title="Engineer",
                provenance="exp-rich",
                bullets=[
                    TailoredBullet(text=f"Rich {index}", provenance=f"rich-{index}")
                    for index in range(rich)
                ],
            ),
            TailoredExperience(
                company="Beta",
                title="Engineer",
                provenance="exp-thin",
                bullets=[
                    TailoredBullet(text=f"Thin {index}", provenance=f"thin-{index}")
                    for index in range(thin)
                ],
            ),
        ],
        projects=[
            TailoredProject(
                name="Project one",
                provenance="prj-one",
                bullets=[
                    TailoredBullet(text=f"Project {index}", provenance=f"project-{index}")
                    for index in range(project)
                ],
            )
        ] if project else [],
    )


def test_depth_critique_measures_selected_owners_and_is_advisory():
    budget = LengthBudget(max_experiences=2, max_projects=1, max_evidence_owners=3)

    critique = depth_critique(_resume(), _facts(), budget)

    assert critique is not None
    assert critique.reviewer == DEPTH_REVIEWER
    assert critique.passed is True
    assert critique.score == 100
    assert critique.owners_total == 3
    assert critique.owners_met == 3
    assert not [issue for issue in critique.issues if issue.severity is Severity.major]


def test_depth_critique_reports_under_rendered_and_absent_planned_owners():
    budget = LengthBudget(max_experiences=2, max_projects=1, max_evidence_owners=3)

    critique = depth_critique(_resume(rich=1, project=0), _facts(), budget)

    assert critique is not None
    majors = [issue for issue in critique.issues if issue.severity is Severity.major]
    assert len(majors) == 2
    assert any("exp-rich" in issue.message and "1" in issue.message for issue in majors)
    assert any("prj-one" in issue.message and "absent" in issue.message for issue in majors)
    assert critique.score == 33


def test_depth_critique_ignores_owners_excluded_by_the_budget():
    budget = LengthBudget(max_experiences=1, max_projects=0, max_evidence_owners=1)

    critique = depth_critique(_resume(rich=5, project=0), _facts(), budget)

    assert critique is not None
    assert critique.score == 100
    assert all("exp-thin" not in issue.message for issue in critique.issues)
    assert all("exp-excluded" not in issue.message for issue in critique.issues)


def test_depth_critique_marks_monotone_rendered_aspects_minor_only():
    budget = LengthBudget(max_experiences=1, max_projects=0, max_evidence_owners=1)

    critique = depth_critique(_resume(rich=5, project=0), _facts(repeated_aspect=True), budget)

    assert critique is not None
    assert any(issue.severity is Severity.minor for issue in critique.issues)
    assert not [issue for issue in critique.issues if issue.severity is Severity.major]


def test_depth_critique_returns_none_without_a_planned_owner():
    empty = ProfileFacts(contact=Contact(name="Ada"))

    assert depth_critique(ResumeContent(contact=Contact(name="Ada")), empty, LengthBudget()) is None
