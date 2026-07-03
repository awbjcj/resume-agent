from resume_agent.models.profile import Contact, Experience, ProfileFacts, Project
from resume_agent.profile.synthesis import (
    SynthesizedClaim,
    SynthesizedEntry,
    SynthesizedFragment,
    compose_synthesis_input,
    profile_skeleton,
)


class _FakeResult:
    def __init__(self, content):
        self.content = content


class _FakeAgent:
    def __init__(self, content):
        self._content = content
        self.calls = 0
        self.prompts: list[str] = []

    def run(self, prompt):
        self.calls += 1
        self.prompts.append(prompt)
        return _FakeResult(self._content)

    async def arun(self, prompt):
        return self.run(prompt)


def _facts():
    return ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[Experience(id="exp1", company="Acme", title="Engineer",
                               start="2022", end=None, current=True)],
        projects=[Project(id="proj1", name="Engine")],
    )


def test_profile_skeleton_lists_anchor_candidates():
    rows = profile_skeleton(_facts())
    assert {"id": "exp1", "kind": "experience", "company": "Acme",
            "title": "Engineer", "start": "2022", "end": None} in rows
    assert {"id": "proj1", "kind": "project", "name": "Engine"} in rows


def test_compose_synthesis_input_contains_skeleton_and_document():
    prompt = compose_synthesis_input("DECK TEXT HERE", profile_skeleton(_facts()))
    assert "exp1" in prompt
    assert "DECK TEXT HERE" in prompt


def test_fact_item_synthesized_defaults_false_and_round_trips():
    project = Project(name="Engine")
    assert project.synthesized is False
    reloaded = Project.model_validate_json(
        Project(name="Engine", synthesized=True).model_dump_json()
    )
    assert reloaded.synthesized is True


def test_synthesized_fragment_models_validate():
    fragment = SynthesizedFragment(entries=[SynthesizedEntry(
        kind="experience_bullets", anchor_id="exp1",
        claims=[SynthesizedClaim(text="Cut latency 30%", support=["latency fell 30%"])],
        tech=["Kubernetes"],
    )])
    assert fragment.entries[0].claims[0].support == ["latency fell 30%"]
