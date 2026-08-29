import pytest

from resume_agent.models.profile import Bullet, Contact, Experience, ProfileFacts, Skill
from resume_agent.profile.inference import (
    InferredSkill,
    InferredSkills,
    apply_inferred,
    infer_skills,
)


class _FakeResult:
    def __init__(self, content):
        self.content = content


class _FakeAgent:
    def __init__(self, content):
        self._content = content

    def run(self, prompt):
        return _FakeResult(self._content)

    async def arun(self, prompt):
        return self.run(prompt)


def _facts():
    bullet = Bullet(text="Mentored 3 junior engineers")
    return (
        ProfileFacts(
            contact=Contact(name="Ada"),
            experience=[Experience(company="Acme", title="Engineer", bullets=[bullet])],
            skills={"Languages": [Skill(name="Python")]},
        ),
        bullet.id,
    )


def test_apply_inferred_appends_evidence_backed_skill():
    facts, bullet_id = _facts()
    updated, added = apply_inferred(
        facts,
        [
            InferredSkill(
                name="Mentorship", category="soft", evidence_fact_ids=[bullet_id]
            )
        ],
    )
    assert added == ["Mentorship"]
    inferred = updated.skills["soft"][0]
    assert inferred.name == "Mentorship"
    assert inferred.inferred is True
    assert inferred.evidence_fact_ids == [bullet_id]
    assert inferred.source == facts.experience[0].bullets[0].source


def test_apply_inferred_drops_unresolvable_or_empty_evidence():
    facts, _ = _facts()
    updated, added = apply_inferred(
        facts,
        [
            InferredSkill(
                name="Leadership", category="soft", evidence_fact_ids=["nope"]
            ),
            InferredSkill(name="Ownership", category="soft"),
        ],
    )
    assert added == []
    assert "soft" not in updated.skills


def test_apply_inferred_skips_existing_literal_name_or_alias():
    facts, bullet_id = _facts()
    facts.skills["Languages"][0].aliases = ["Py"]
    updated, added = apply_inferred(
        facts,
        [
            InferredSkill(
                name="python", category="hard", evidence_fact_ids=[bullet_id]
            ),
            InferredSkill(name="py", category="hard", evidence_fact_ids=[bullet_id]),
        ],
    )
    assert added == []
    assert "hard" not in updated.skills


def test_apply_inferred_is_idempotent():
    facts, bullet_id = _facts()
    inferred = [
        InferredSkill(name="Mentorship", category="soft", evidence_fact_ids=[bullet_id])
    ]
    once, _ = apply_inferred(facts, inferred)
    twice, _ = apply_inferred(once, inferred)
    assert len(twice.skills["soft"]) == 1
    assert once.skills["soft"][0].id == twice.skills["soft"][0].id


def test_inferred_id_changes_when_evidence_changes():
    facts, first_id = _facts()
    second = Bullet(text="Coached an intern")
    facts.experience[0].bullets.append(second)
    first, _ = apply_inferred(
        facts,
        [
            InferredSkill(
                name="Mentorship", category="soft", evidence_fact_ids=[first_id]
            )
        ],
    )
    second_result, _ = apply_inferred(
        facts,
        [
            InferredSkill(
                name="Mentorship", category="soft", evidence_fact_ids=[second.id]
            )
        ],
    )
    assert first.skills["soft"][0].id != second_result.skills["soft"][0].id


def test_inferred_id_ignores_duplicate_evidence_order():
    facts, first_id = _facts()
    second = Bullet(text="Coached an intern")
    facts.experience[0].bullets.append(second)
    forward, _ = apply_inferred(
        facts,
        [
            InferredSkill(
                name="Mentorship",
                category="soft",
                evidence_fact_ids=[first_id, second.id, first_id],
            )
        ],
    )
    reverse, _ = apply_inferred(
        facts,
        [
            InferredSkill(
                name="Mentorship",
                category="soft",
                evidence_fact_ids=[second.id, first_id],
            )
        ],
    )
    assert forward.skills["soft"][0].id == reverse.skills["soft"][0].id


def test_infer_skills_type_checks():
    facts, bullet_id = _facts()
    agent = _FakeAgent(
        InferredSkills(
            skills=[
                InferredSkill(
                    name="Mentorship",
                    category="soft",
                    evidence_fact_ids=[bullet_id],
                )
            ]
        )
    )
    assert [skill.name for skill in infer_skills(facts, agent)] == ["Mentorship"]

    with pytest.raises(TypeError, match="Expected InferredSkills"):
        infer_skills(facts, _FakeAgent("bad"))
