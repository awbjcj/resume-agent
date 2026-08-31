"""Lock the approved agent/tool and redaction boundaries."""

from pathlib import Path

from resume_tailor_harness.career_skills.agno import run_meta_payload, skill_kwargs
from resume_tailor_harness.career_skills.models import AgentFamily, AgentRunMeta
from resume_tailor_harness.career_skills.registry import CareerSkillRegistry
from resume_tailor_harness.h1b.mcp import H1B_INCLUDE_TOOLS


class _Runner:
    def __init__(self, run_meta: AgentRunMeta) -> None:
        self.run_meta = run_meta

    def run(self, prompt: str) -> object:
        return prompt

    async def arun(self, prompt: str) -> object:
        return prompt


def _career_skill():
    return CareerSkillRegistry.from_paths("skills", "skills-lock.json").require(
        "salary-negotiation-prep", family=AgentFamily.CAREER_LAB, use="career_lab"
    )


def test_only_allowlisted_h1b_tools_are_exposed():
    assert set(H1B_INCLUDE_TOOLS) == {
        "get_company_stats",
        "search_h1b_jobs",
        "get_available_data",
        "get_company_sponsorship_trend",
    }


def test_persona_skill_attachment_has_exactly_one_local_loader():
    kwargs = skill_kwargs(_career_skill())
    assert len(kwargs["skills"].loaders) == 1
    assert not kwargs.get("tools")


def test_run_metadata_is_redacted_to_identity_only():
    skill = _career_skill()
    runner = _Runner(
        AgentRunMeta(
            agent_family=AgentFamily.CAREER_LAB,
            prompt_policy_version="career-lab-v1",
            model_id="test-model",
            skill_ref=skill.ref,
        )
    )
    payload = run_meta_payload(runner)[0]
    skill_payload = payload["skill"]
    assert isinstance(skill_payload, dict)
    assert skill_payload == {
        "name": skill.ref.name,
        "version": skill.ref.version,
        "sha256": skill.ref.sha256,
    }
    assert "body" not in skill_payload
    assert "prompt" not in payload


def test_mcp_boundary_does_not_leak_into_other_agent_families():
    roots = [
        Path("src/resume_tailor_harness/career_lab"),
        Path("src/resume_tailor_harness/discovery"),
        Path("src/resume_tailor_harness/tailor"),
        Path("src/resume_tailor_harness/cover_letter"),
        Path("src/resume_tailor_harness/interview"),
    ]
    offenders = [
        str(path)
        for root in roots
        for path in root.rglob("*.py")
        if "MCPTools" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_career_lab_prompt_labels_user_controlled_data():
    source = Path("src/resume_tailor_harness/services/career_lab.py").read_text(encoding="utf-8")
    assert "MESSAGE (UNTRUSTED)" in source
    assert "TYPED CONTEXT PROJECTION (UNTRUSTED)" in source
    assert "Do not claim external actions" in source
