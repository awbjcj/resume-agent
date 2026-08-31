import asyncio

import pytest
from pydantic import ValidationError

from resume_tailor_harness.models.base import Source
from resume_tailor_harness.models.profile import Project, Skill
from resume_tailor_harness.profile.project_extractor import (
    _INSTRUCTIONS,
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
            "name": "resume-tailor-harness",
            "repo_url": "https://github.com/me/resume-tailor-harness",
            "tech": ["Python"],
            "highlights": [{"text": "Automated releases"}],
            "experience": [{"company": "Injected"}],
        }
    )
    skill = Skill.model_validate(
        {
            "name": "FastAPI",
            "category": "hard",
            "inferred": True,
            "evidence_fact_ids": ["project:resume-tailor-harness:highlight:1"],
            "employer": "Injected",
        }
    )
    return ProjectDocFacts(project=project, skills={"backend": [skill]})


def test_project_doc_schema_forbids_foreign_top_level_sections():
    with pytest.raises(ValidationError):
        ProjectDocFacts.model_validate(
            {"project": {"name": "x"}, "experience": [{"company": "Injected"}]}
        )


def test_project_doc_normalizes_tooling_skill_category_to_hard():
    facts = ProjectDocFacts.model_validate(
        {
            "project": {"name": "x"},
            "skills": {"Tooling": [{"name": "Docker", "category": "tooling"}]},
        }
    )

    assert facts.skills["Tooling"][0].category == "hard"


def test_project_doc_rejects_unknown_skill_category():
    with pytest.raises(ValidationError, match="invented"):
        ProjectDocFacts.model_validate(
            {
                "project": {"name": "x"},
                "skills": {"Tooling": [{"name": "Docker", "category": "invented"}]},
            }
        )


def test_project_extractor_prompt_distinguishes_groups_from_skill_categories():
    prompt = " ".join(_INSTRUCTIONS)

    assert "hard, soft, or domain" in prompt
    assert "tool or tooling skill must use hard" in prompt


def test_project_extractor_prompt_forbids_model_generated_evidence_ids():
    prompt = " ".join(_INSTRUCTIONS)

    assert "evidence_fact_ids empty" in prompt
    assert "inferred false" in prompt


def test_project_projection_strips_nested_extras_and_sets_source():
    facts = project_facts_to_profile(project_doc(), source=Source.github)
    assert facts.projects[0].source == Source.github
    assert facts.projects[0].highlights[0].source == Source.github
    assert facts.skills["backend"][0].source == Source.github
    assert facts.skills["backend"][0].inferred is False
    assert facts.skills["backend"][0].evidence_fact_ids == []
    assert "experience" not in (facts.projects[0].model_extra or {})
    assert "employer" not in (facts.skills["backend"][0].model_extra or {})
    assert (
        facts.experience == [] and facts.education == [] and facts.certifications == []
    )


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
