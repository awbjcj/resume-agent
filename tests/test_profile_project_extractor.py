import asyncio

import pytest
from pydantic import ValidationError

from resume_agent.models.base import Source
from resume_agent.models.profile import Project, Skill
from resume_agent.profile.project_extractor import (
    ProjectDocFacts,
    aextract_project_facts,
    project_facts_to_profile,
)


class FakeResult:
    def __init__(self, content):
        self.content = content


class FakeAgent:
    def __init__(self, content):
        self.content = content

    def run(self, prompt):
        return FakeResult(self.content)

    async def arun(self, prompt):
        return FakeResult(self.content)


def project_doc() -> ProjectDocFacts:
    project = Project.model_validate(
        {
            "name": "resume-agent",
            "repo_url": "https://github.com/me/resume-agent",
            "tech": ["Python"],
            "experience": [{"company": "Injected"}],
        }
    )
    skill = Skill.model_validate({"name": "FastAPI", "employer": "Injected"})
    return ProjectDocFacts(project=project, skills={"backend": [skill]})


def test_project_doc_schema_forbids_foreign_top_level_sections():
    with pytest.raises(ValidationError):
        ProjectDocFacts.model_validate(
            {"project": {"name": "x"}, "experience": [{"company": "Injected"}]}
        )


def test_project_projection_strips_nested_extras_and_sets_source():
    facts = project_facts_to_profile(project_doc(), source=Source.github)
    assert facts.projects[0].source == Source.github
    assert facts.skills["backend"][0].source == Source.github
    assert "experience" not in facts.projects[0].model_extra
    assert "employer" not in facts.skills["backend"][0].model_extra
    assert facts.experience == [] and facts.education == [] and facts.certifications == []


def test_async_project_extraction_validates_type():
    sem = asyncio.Semaphore(1)
    facts = asyncio.run(
        aextract_project_facts(
            "doc", FakeAgent(project_doc()), source=Source.manual, sem=sem
        )
    )
    assert facts.projects[0].source == Source.manual
    with pytest.raises(TypeError, match="ProjectDocFacts"):
        asyncio.run(
            aextract_project_facts(
                "doc", FakeAgent("wrong"), source=Source.manual, sem=sem
            )
        )
