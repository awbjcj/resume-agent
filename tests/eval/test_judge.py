import pytest

from evals.judge import (
    DimensionScore,
    JudgeVerdict,
    build_judge_agent,
    cl_judge_prompt_hash,
    compose_cl_judge_input,
    compose_judge_input,
    judge_prompt_hash,
    validate_judge_verdict,
)
from resume_agent.models.cover_letter import CoverLetterContent
from resume_agent.models.profile import Contact, ProfileFacts
from resume_agent.models.resume import ResumeContent, TailoredBullet, TailoredExperience


def _content() -> ResumeContent:
    return ResumeContent(
        contact=Contact(name="Ada"),
        summary="Backend engineer.",
        experience=[
            TailoredExperience(
                company="AE",
                title="Eng",
                provenance="e1",
                bullets=[TailoredBullet(text="Built REST API", provenance="b1")],
            )
        ],
    )


def test_compose_judge_input_has_resume_jd_and_rubric():
    text = compose_judge_input(_content(), "Backend role", ["relevance", "impact"])

    assert "Built REST API" in text
    assert "Backend role" in text
    assert "relevance" in text


def test_compose_judge_input_omits_profile_and_trap_labels():
    text = compose_judge_input(_content(), "jd", ["relevance"])

    assert "CANDIDATE PROFILE" not in text
    assert "KNOWN TRAPS" not in text


def test_judge_verdict_schema():
    verdict = JudgeVerdict(output_quality=88, dimensions=[], summary="ok")

    assert verdict.output_quality == 88


def test_judge_verdict_must_cover_rubric_exactly():
    with pytest.raises(ValueError):
        validate_judge_verdict(
            JudgeVerdict(output_quality=88, dimensions=[]), ["relevance"]
        )


def test_judge_verdict_accepts_exact_rubric():
    verdict = JudgeVerdict(
        output_quality=88,
        dimensions=[
            DimensionScore(dimension="relevance", score=88, rationale="Strong fit")
        ],
    )

    validate_judge_verdict(verdict, ["relevance"])


def test_judge_prompt_hash_is_stable_sha256():
    assert len(judge_prompt_hash()) == 64
    assert judge_prompt_hash() == judge_prompt_hash()


def test_build_judge_agent_is_runnable():
    agent = build_judge_agent("anthropic:claude-x")

    assert hasattr(agent, "run")
    assert hasattr(agent, "arun")


def test_compose_cl_judge_input_has_grounding_and_style_inputs():
    content = CoverLetterContent(
        contact=Contact(name="Ada"),
        greeting="Hi,",
        closing="Bye",
    )
    profile = ProfileFacts(
        contact=Contact(name="Ada"),
        summary="Backend engineer",
    )

    text = compose_cl_judge_input(
        content,
        profile,
        "the jd",
        ["grounding", "tone"],
        "Write crisply.",
    )

    assert "COVER LETTER UNDER REVIEW (JSON):" in text
    assert "CANDIDATE PROFILE (JSON):" in text
    assert "Backend engineer" in text
    assert "JOB DESCRIPTION:\nthe jd" in text
    assert "HOUSE STYLE:\nWrite crisply." in text
    assert "RUBRIC DIMENSIONS:\ngrounding, tone" in text


def test_cl_judge_prompt_hash_is_stable_and_distinct():
    assert cl_judge_prompt_hash() == cl_judge_prompt_hash()
    assert cl_judge_prompt_hash() != judge_prompt_hash()
