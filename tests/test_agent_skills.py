from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from resume_agent.career_skills.agno import (
    AgentCacheKey,
    SkilledAgentPool,
    run_meta_payload,
    skill_kwargs,
)
from resume_agent.career_skills.models import AgentFamily, AgentRunMeta, SkillRef
from resume_agent.career_skills.registry import CareerSkillRegistry
from resume_agent.llm_runner import AgentRunner


@pytest.fixture
def verified_skill():
    registry = CareerSkillRegistry.from_paths(Path("skills"), Path("skills-lock.json"))
    return registry.require(
        "job-description-analyzer",
        family=AgentFamily.JOB_ANALYSIS,
        use="extract",
    )


def test_skill_kwargs_loads_only_the_selected_directory(verified_skill):
    kwargs = skill_kwargs(verified_skill)
    loaders = kwargs["skills"].loaders

    assert len(loaders) == 1
    loader_path = getattr(loaders[0], "path", None)
    assert loader_path is not None
    assert Path(str(loader_path)).resolve() == verified_skill.directory.resolve()


def test_skilled_pool_reuses_stable_configuration():
    pool = SkilledAgentPool()
    key = AgentCacheKey(
        family=AgentFamily.JOB_ANALYSIS,
        skill_sha256="a" * 64,
        model_id="test-model",
        output_schema="JobCriteriaExtract",
        prompt_policy_version="job-extract-v1",
    )
    calls = 0

    class _FakeRunner:
        def run(self, prompt: str) -> object:
            return prompt

        async def arun(self, prompt: str) -> object:
            return prompt

    def builder() -> _FakeRunner:
        nonlocal calls
        calls += 1
        return _FakeRunner()

    first = pool.get(key, builder)
    second = pool.get(key, builder)

    assert first is second
    assert calls == 1


def test_agent_cache_key_is_immutable():
    key = AgentCacheKey(
        family=AgentFamily.JOB_ANALYSIS,
        skill_sha256=None,
        model_id="test-model",
        output_schema=None,
        prompt_policy_version="v1",
    )
    with pytest.raises(FrozenInstanceError):
        key.model_id = "other"  # type: ignore[misc]


def test_run_meta_is_read_only_and_payload_excludes_content():
    meta = AgentRunMeta(
        agent_family=AgentFamily.JOB_ANALYSIS,
        prompt_policy_version="job-extract-v1",
        model_id="test-model",
        skill_ref=SkillRef(
            name="job-description-analyzer",
            version="2026-08-02",
            sha256="a" * 64,
            family=AgentFamily.JOB_ANALYSIS,
        ),
    )
    runner = AgentRunner(object(), run_meta=meta)

    assert runner.run_meta is meta
    assert run_meta_payload(runner) == [
        {
            "agentFamily": "job_analysis",
            "promptPolicyVersion": "job-extract-v1",
            "modelId": "test-model",
            "skill": {
                "name": "job-description-analyzer",
                "version": "2026-08-02",
                "sha256": "a" * 64,
            },
        }
    ]
