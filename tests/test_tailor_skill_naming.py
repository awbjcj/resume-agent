from resume_agent.models.profile import Contact, ProfileFacts, Skill
from resume_agent.models.resume import ResumeContent, TailoredSkill
from resume_agent.models.review import Severity
from resume_agent.tailor.skill_naming import (
    SKILL_NAMING_REVIEWER,
    skill_naming_critique,
    split_name,
)


def _facts() -> ProfileFacts:
    return ProfileFacts(
        contact=Contact(name="Ada"),
        skills={
            "hard": [
                Skill(id="s1", name="LLM Agents", aliases=["llm", "ai agents"]),
                Skill(id="s2", name="LangChain"),
                Skill(id="s3", name="Amazon Web Services"),
                Skill(id="s4", name="Research & Development"),
            ]
        },
    )


def _facts_with_forbidden_inferred_match() -> ProfileFacts:
    facts = _facts()
    return facts.model_copy(
        update={
            "skills": {
                **facts.skills,
                "soft": [
                    Skill(
                        id="inferred-soft-langchain",
                        name="LangChain",
                        inferred=True,
                        category="soft",
                        evidence_fact_ids=["s1"],
                    )
                ],
            }
        }
    )


def _resume(*skills: TailoredSkill) -> ResumeContent:
    return ResumeContent(contact=Contact(name="Ada"), skills={"Core": list(skills)})


def test_compound_name_citing_one_fact_blocks():
    content = _resume(TailoredSkill(name="AI/LLM Agents & LangChain", provenance="s1"))

    critique = skill_naming_critique(content, _facts())

    assert critique.reviewer == SKILL_NAMING_REVIEWER
    assert critique.passed is False
    assert critique.score == 0
    blocking = [i for i in critique.issues if i.severity is Severity.blocking]
    assert blocking, "a compound name must raise a blocking issue"
    assert "LangChain" in " ".join(i.message for i in blocking)
    assert blocking[0].location == "skills/Core/AI/LLM Agents & LangChain"


def test_compound_suggestion_names_fact_id_for_extra_segment():
    content = _resume(TailoredSkill(name="LLM Agents & LangChain", provenance="s1"))

    critique = skill_naming_critique(content, _facts())

    blocking = [i for i in critique.issues if i.severity is Severity.blocking]
    assert "LangChain" in (blocking[0].suggestion or "")
    assert "s2" in (blocking[0].suggestion or "")


def test_compound_suggestion_omits_forbidden_inferred_fact_id():
    content = _resume(TailoredSkill(name="LLM Agents & LangChain", provenance="s1"))

    critique = skill_naming_critique(content, _facts_with_forbidden_inferred_match())

    blocking = [i for i in critique.issues if i.severity is Severity.blocking]
    suggestion = blocking[0].suggestion or ""
    assert "s2" in suggestion, "the usable literal fact must remain identifiable"
    assert "inferred-soft-langchain" not in suggestion


def test_the_same_two_skills_as_separate_entries_pass():
    content = _resume(
        TailoredSkill(name="LLM Agents", provenance="s1"),
        TailoredSkill(name="LangChain", provenance="s2"),
    )

    critique = skill_naming_critique(content, _facts())

    assert critique.passed is True
    assert critique.score == 100
    assert critique.issues == []


def test_alias_rename_is_legal():
    content = _resume(TailoredSkill(name="AI Agents", provenance="s1"))

    assert skill_naming_critique(content, _facts()).issues == []


def test_atomic_mismatch_is_major_not_blocking():
    content = _resume(TailoredSkill(name="AWS", provenance="s3"))

    critique = skill_naming_critique(content, _facts())

    assert critique.passed is True
    assert [i.severity for i in critique.issues] == [Severity.major]


def test_fact_name_containing_a_separator_is_not_split():
    """Regression guard: 'Research & Development' cited and displayed verbatim
    must not be split into two unresolvable segments."""
    content = _resume(TailoredSkill(name="Research & Development", provenance="s4"))

    assert skill_naming_critique(content, _facts()).issues == []


def test_unknown_provenance_id_is_left_to_the_provenance_gate():
    content = _resume(TailoredSkill(name="Rust & Go", provenance="nope"))

    assert skill_naming_critique(content, _facts()).issues == []


def test_split_name_drops_empty_segments_and_parentheses():
    assert split_name("Unit Testing (pytest, MATLAB Unit Test)") == [
        "Unit Testing",
        "pytest",
        "MATLAB Unit Test",
    ]
