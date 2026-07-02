import asyncio

from resume_agent.models.job import JobCriteria
from resume_agent.models.match_plan import MatchPlan, MatchPlanRequirement
from resume_agent.models.profile import Bullet, Contact, Experience, ProfileFacts
from resume_agent.profile.matrix import MatrixRow, SkillMatch, SkillMatchContext
from resume_agent.tailor.match_plan import (
    amatch_plan,
    build_match_plan_agent,
    compose_match_plan_input,
    match_plan,
    normalize_match_plan,
)


class _Result:
    def __init__(self, content):
        self.content = content


class _Agent:
    def run(self, prompt):
        return _Result(
            MatchPlan(
                requirements=[
                    MatchPlanRequirement(
                        jd_requirement="Python",
                        supporting_fact_ids=["e1b1"],
                        emphasis="lead with API scale",
                    )
                ]
            )
        )

    async def arun(self, prompt):
        return self.run(prompt)


def _facts() -> ProfileFacts:
    return ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[
            Experience(
                id="e1",
                company="AE",
                title="Eng",
                bullets=[Bullet(id="e1b1", text="Built API")],
            )
        ],
    )


def test_compose_match_plan_input_has_jd_criteria_and_profile():
    text = compose_match_plan_input(
        "Backend role", JobCriteria(must_have_skills=["Python"]), _facts()
    )
    assert "Backend role" in text and "Python" in text
    assert "CANDIDATE PROFILE" in text
    assert "SKILL MATCH CONTEXT" not in text


def test_compose_match_plan_input_appends_deterministic_skill_context():
    context = SkillMatchContext(
        matches=[
            SkillMatch(
                requirement="Python",
                source="must",
                coverage="covered",
                row=MatrixRow(key="python", display="Python", strength=3.0),
            )
        ]
    )
    text = compose_match_plan_input(
        "JD",
        JobCriteria(),
        ProfileFacts(contact=Contact(name="Ada")),
        skill_context=context,
    )
    assert "SKILL MATCH CONTEXT (JSON):" in text
    assert '"coverage":"covered"' in text
    assert '"python"' in text
    assert text.index("SKILL MATCH CONTEXT") < text.index("JOB DESCRIPTION")


def test_match_plan_sync_and_async_return_structured_plan():
    assert match_plan("x", _Agent()).requirements[0].supporting_fact_ids == ["e1b1"]
    plan = asyncio.run(amatch_plan("x", _Agent(), sem=asyncio.Semaphore(1)))
    assert plan.requirements[0].jd_requirement == "Python"


def test_normalize_match_plan_removes_unknown_ids_and_repairs_gaps():
    plan = MatchPlan(
        requirements=[
            MatchPlanRequirement(
                jd_requirement="Python",
                supporting_fact_ids=["e1b1", "invented"],
                emphasis="use the supported API fact",
            ),
            MatchPlanRequirement(
                jd_requirement="Kubernetes",
                supporting_fact_ids=["invented"],
                emphasis="do not fabricate",
            ),
            MatchPlanRequirement(
                jd_requirement="Go",
                supporting_fact_ids=["e1b1"],
                emphasis="valid support overrides a stale gap flag",
                gap=True,
            ),
        ]
    )

    normalized = normalize_match_plan(plan, _facts())

    assert normalized.requirements[0].supporting_fact_ids == ["e1b1"]
    assert normalized.requirements[0].gap is False
    assert normalized.requirements[1].supporting_fact_ids == []
    assert normalized.requirements[1].gap is True
    assert normalized.requirements[2].supporting_fact_ids == ["e1b1"]
    assert normalized.requirements[2].gap is False


def test_build_match_plan_agent_is_runnable(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    agent = build_match_plan_agent("anthropic:claude-test")
    assert hasattr(agent, "run") and hasattr(agent, "arun")
