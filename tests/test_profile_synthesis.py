from resume_agent.models.profile import Contact, Experience, ProfileFacts, Project
from resume_agent.profile.synthesis import (
    SynthesizedClaim,
    SynthesizedEntry,
    SynthesizedFragment,
    compose_synthesis_input,
    deterministic_failures,
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


_SOURCE = (
    "Slide 3: The billing rewrite at Acme cut p99 latency 30% across 4 services.\n"
    "We migrated the pipeline to Kubernetes in 2024."
)


def _claim(text, support=None):
    return SynthesizedClaim(text=text, support=support or ["cut p99 latency 30%"])


def test_supported_claim_passes():
    claim = _claim("Cut p99 latency 30% across 4 services",
                   support=["cut p99 latency 30% across 4 services"])
    assert deterministic_failures(claim, _SOURCE) == []


def test_unsupported_number_fails():
    failures = deterministic_failures(_claim("Cut p99 latency 45%"), _SOURCE)
    assert any("45%" in reason for reason in failures)


def test_unsupported_proper_noun_fails():
    failures = deterministic_failures(
        _claim("Migrated the pipeline to Terraform",
               support=["migrated the pipeline to Kubernetes"]),
        _SOURCE,
    )
    assert any("Terraform" in reason for reason in failures)


def test_sentence_initial_capital_is_exempt():
    claim = _claim("Migrated the pipeline to Kubernetes",
                   support=["migrated the pipeline to Kubernetes in 2024"])
    assert deterministic_failures(claim, _SOURCE) == []


def test_excerpt_must_be_a_real_substring():
    claim = SynthesizedClaim(text="Cut latency", support=["latency dropped in half"])
    failures = deterministic_failures(claim, _SOURCE)
    assert any("excerpt" in reason for reason in failures)


def test_excerpt_whitespace_is_normalized():
    claim = SynthesizedClaim(
        text="Cut p99 latency 30%",
        support=["cut p99   latency\n30%"],
    )
    assert deterministic_failures(claim, _SOURCE) == []


def test_missing_support_fails():
    failures = deterministic_failures(SynthesizedClaim(text="Cut latency"), _SOURCE)
    assert failures == ["no supporting excerpt"]


def test_unknown_tech_token_fails():
    failures = deterministic_failures(
        _claim("Cut p99 latency 30%"), _SOURCE, tech=["Kubernetes", "Terraform"]
    )
    assert any("Terraform" in reason for reason in failures)
    assert not any("Kubernetes" in reason for reason in failures)
