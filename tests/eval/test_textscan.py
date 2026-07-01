from evals.schema import Trap
from evals.textscan import resume_text, term_present, trap_terms_hit
from resume_agent.models.profile import Contact
from resume_agent.models.resume import (
    ResumeContent,
    TailoredBullet,
    TailoredExperience,
    TailoredSkill,
)


def _resume(*bullets: str, skill: str | None = None) -> ResumeContent:
    skills = {"core": [TailoredSkill(name=skill, provenance="s1")]} if skill else {}
    return ResumeContent(
        contact=Contact(name="Ada"),
        summary="Backend engineer.",
        experience=[
            TailoredExperience(
                company="AE",
                title="Engineer",
                provenance="e1",
                bullets=[
                    TailoredBullet(text=bullet, provenance="b1") for bullet in bullets
                ],
            )
        ],
        skills=skills,
    )


def test_resume_text_includes_bullets_and_skills():
    text = resume_text(_resume("Built a Kubernetes operator", skill="Docker"))

    assert "kubernetes operator" in text
    assert "docker" in text


def test_term_present_is_word_boundary():
    assert term_present("i write javascript daily", "javascript") is True
    assert term_present("i write javascript daily", "java") is False
    assert term_present("deployed on k8s", "K8s") is True


def test_term_present_matches_terms_ending_in_non_word_char():
    # A boundary assertion belongs only on a side whose edge is a word char;
    # "saved $" must still match a real dollar amount like "saved $30,000".
    assert term_present("reduced spend; saved $30,000 annually", "saved $") is True
    assert term_present("saved $1M in cloud costs", "saved $") is True


def test_trap_terms_hit_returns_present_forbidden_terms():
    traps = [
        Trap(
            id="k8s",
            kind="missing_skill",
            forbidden_terms=["Kubernetes", "k8s"],
            description="x",
            probe_claim="Built Kubernetes clusters",
            probe_provenance="b1",
        )
    ]

    hit = trap_terms_hit(_resume("Built a Kubernetes operator"), traps)

    assert hit == ["Kubernetes"]


def test_trap_terms_hit_clean_resume_is_empty():
    traps = [
        Trap(
            id="k8s",
            kind="missing_skill",
            forbidden_terms=["Kubernetes"],
            description="x",
            probe_claim="Built Kubernetes clusters",
            probe_provenance="b1",
        )
    ]

    assert trap_terms_hit(_resume("Built a REST API"), traps) == []
