from resume_tailor_harness.models.profile import (
    Bullet,
    Contact,
    Experience,
    ProfileFacts,
    Project,
)
from resume_tailor_harness.profile.aspect_classifier import (
    AspectAssignment,
    AspectAssignments,
    classify_aspects,
)


class _Result:
    def __init__(self, content):
        self.content = content


class _Agent:
    def __init__(self, content):
        self.content = content
        self.prompts: list[str] = []

    def run(self, prompt):
        self.prompts.append(prompt)
        return _Result(self.content)

    async def arun(self, prompt):
        return self.run(prompt)


def _facts() -> ProfileFacts:
    return ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[
            Experience(
                id="e1",
                company="Acme",
                title="Engineer",
                bullets=[
                    Bullet(id="b1", text="Built the platform"),
                    Bullet(id="b2", text="Led the rollout", aspect="leadership"),
                ],
            )
        ],
        projects=[
            Project(
                id="p1",
                name="Dashboard",
                highlights=[Bullet(id="h1", text="Automated reporting")],
            )
        ],
    )


def test_classifier_only_sends_and_updates_unclassified_bullets():
    agent = _Agent(
        AspectAssignments(
            assignments=[
                AspectAssignment(bullet_id="b1", aspect="technical"),
                AspectAssignment(bullet_id="h1", aspect="tooling"),
                AspectAssignment(bullet_id="unknown", aspect="impact"),
                AspectAssignment(bullet_id="b2", aspect="scope"),
            ]
        )
    )

    classified = classify_aspects(_facts(), agent)

    assert len(agent.prompts) == 1
    assert '"id": "b1"' in agent.prompts[0]
    assert '"id": "h1"' in agent.prompts[0]
    assert '"id": "b2"' not in agent.prompts[0]
    assert classified.experience[0].bullets[0].aspect == "technical"
    assert classified.experience[0].bullets[1].aspect == "leadership"
    assert classified.projects[0].highlights[0].aspect == "tooling"


def test_classifier_skips_the_model_when_all_bullets_already_have_aspects():
    facts = _facts()
    facts.experience[0].bullets[0].aspect = "technical"
    facts.projects[0].highlights[0].aspect = "tooling"
    agent = _Agent(AspectAssignments())

    assert classify_aspects(facts, agent) == facts
    assert agent.prompts == []
