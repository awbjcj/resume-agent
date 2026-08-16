from resume_agent.models.profile import Contact, Experience, ProfileFacts, Project
from resume_agent.profile.corpus import SourceDoc
from resume_agent.profile.synthesis import (
    ClaimVerdict,
    ClaimVerdicts,
    SynthesizedClaim,
    SynthesizedEntry,
    SynthesizedFragment,
    compose_synthesis_input,
    deterministic_failures,
    fragment_to_facts,
    profile_skeleton,
    synthesize_document,
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


class _SeqAgent:
    """Returns queued contents in order; the last one repeats."""

    def __init__(self, contents):
        self._contents = list(contents)
        self.calls = 0
        self.prompts: list[str] = []

    def run(self, prompt):
        self.calls += 1
        self.prompts.append(prompt)
        content = (
            self._contents.pop(0) if len(self._contents) > 1 else self._contents[0]
        )
        return _FakeResult(content)

    async def arun(self, prompt):
        return self.run(prompt)


def _doc(anchor=None):
    return SourceDoc(id="deck-1", filename="deck.pptx", sha256="0" * 64,
                     added_at="2026-07-03T00:00:00+00:00", mode="synthesis",
                     anchor=anchor)


_DECK = "The billing rewrite cut p99 latency 30%. Built on Kubernetes."


def _entry(text="Cut p99 latency 30%", support=("cut p99 latency 30%",),
           anchor_id="exp1", tech=()):
    return SynthesizedEntry(
        kind="experience_bullets", anchor_id=anchor_id,
        claims=[SynthesizedClaim(text=text, support=list(support))],
        tech=list(tech),
    )


def _approve_all():
    class _Approve:
        calls = 0

        def run(self, prompt):
            self.calls += 1
            claims = __import__("json").loads(prompt)
            return _FakeResult(ClaimVerdicts(verdicts=[
                ClaimVerdict(index=c["index"], verdict="supported") for c in claims
            ]))

        async def arun(self, prompt):
            return self.run(prompt)

    return _Approve()


def test_happy_path_keeps_verified_claims():
    synthesis = _SeqAgent([SynthesizedFragment(entries=[_entry()])])
    fragment, drops = synthesize_document(
        _doc(), _DECK, profile_skeleton(_facts()), synthesis, _approve_all()
    )
    assert drops == []
    assert fragment.entries[0].claims[0].text == "Cut p99 latency 30%"
    assert synthesis.calls == 1


def test_pinned_anchor_overrides_agent_proposal():
    synthesis = _SeqAgent([SynthesizedFragment(entries=[_entry(anchor_id="wrong")])])
    fragment, _ = synthesize_document(
        _doc(anchor="exp1"), _DECK, profile_skeleton(_facts()), synthesis, _approve_all()
    )
    assert fragment.entries[0].anchor_id == "exp1"


def test_deterministic_failure_triggers_one_repair_round():
    bad = SynthesizedFragment(entries=[_entry(text="Cut p99 latency 45%")])
    fixed = SynthesizedFragment(entries=[_entry(text="Cut p99 latency 30%")])
    synthesis = _SeqAgent([bad, fixed])

    fragment, drops = synthesize_document(
        _doc(), _DECK, profile_skeleton(_facts()), synthesis, _approve_all()
    )
    assert synthesis.calls == 2  # initial + one repair, no more
    assert drops == []
    assert fragment.entries[0].claims[0].text == "Cut p99 latency 30%"
    assert "45%" in synthesis.prompts[1]  # repair prompt carries the reason


def test_still_failing_claim_is_dropped_and_reported():
    bad = SynthesizedFragment(entries=[_entry(text="Cut p99 latency 45%")])
    synthesis = _SeqAgent([bad, bad])
    fragment, drops = synthesize_document(
        _doc(), _DECK, profile_skeleton(_facts()), synthesis, _approve_all()
    )
    assert fragment.entries == []
    assert len(drops) == 1 and "45%" in drops[0]


def test_entailment_unsupported_fails_closed():
    synthesis = _SeqAgent([SynthesizedFragment(entries=[_entry()])])

    class _RejectAll:
        def run(self, prompt):
            claims = __import__("json").loads(prompt)
            return _FakeResult(ClaimVerdicts(verdicts=[
                ClaimVerdict(index=c["index"], verdict="unsupported", reason="overreach")
                for c in claims
            ]))

        async def arun(self, prompt):
            return self.run(prompt)

    fragment, drops = synthesize_document(
        _doc(), _DECK, profile_skeleton(_facts()), synthesis, _RejectAll()
    )
    assert fragment.entries == []
    assert any("overreach" in d for d in drops)


def test_missing_verdict_counts_as_unsupported():
    synthesis = _SeqAgent([SynthesizedFragment(entries=[_entry()])])

    class _Silent:
        def run(self, prompt):
            return _FakeResult(ClaimVerdicts(verdicts=[]))

        async def arun(self, prompt):
            return self.run(prompt)

    fragment, drops = synthesize_document(
        _doc(), _DECK, profile_skeleton(_facts()), synthesis, _Silent()
    )
    assert fragment.entries == []
    assert drops


def test_fragment_to_facts_builds_anchored_stub_with_evidence():
    fragment = SynthesizedFragment(entries=[
        _entry(tech=["Kubernetes"]),
        SynthesizedEntry(kind="skills", category="hard",
                         claims=[SynthesizedClaim(text="Kubernetes",
                                                  support=["Built on Kubernetes"])]),
            SynthesizedEntry(kind="project", title="Billing rewrite",
                         claims=[SynthesizedClaim(text="Rewrote billing", aspect="impact",
                                                  support=["billing rewrite"])]),
    ])
    facts, evidence = fragment_to_facts(_doc(), fragment, profile_skeleton(_facts()))

    stub = facts.experience[0]
    assert stub.id == "exp1" and stub.company == "Acme"
    bullet = stub.bullets[0]
    assert bullet.synthesized and bullet.source_ref == "deck-1"
    assert evidence[bullet.id]["support"] == ["cut p99 latency 30%"]

    skill = facts.skills["hard"][0]
    assert skill.synthesized and skill.id in evidence

    project = facts.projects[0]
    assert project.name == "Billing rewrite" and project.synthesized
    assert [highlight.text for highlight in project.highlights] == ["Rewrote billing"]
    assert project.highlights[0].aspect == "impact"


def test_fragment_to_facts_unknown_anchor_becomes_project():
    fragment = SynthesizedFragment(entries=[_entry(anchor_id="ghost")])
    facts, _ = fragment_to_facts(_doc(), fragment, profile_skeleton(_facts()))
    assert facts.experience == []
    assert len(facts.projects) == 1


def test_fragment_to_facts_ids_are_deterministic():
    fragment = SynthesizedFragment(entries=[_entry()])
    first, _ = fragment_to_facts(_doc(), fragment, profile_skeleton(_facts()))
    second, _ = fragment_to_facts(_doc(), fragment, profile_skeleton(_facts()))
    assert first.experience[0].bullets[0].id == second.experience[0].bullets[0].id


def test_bad_tech_token_does_not_leak_when_a_sibling_claim_survives():
    """An entry-level tech failure must not leak into the final fact, even when
    a different claim in the same entry independently passes verification."""
    entry = SynthesizedEntry(
        kind="experience_bullets", anchor_id="exp1",
        claims=[
            _claim("Cut p99 latency 30%"),
            SynthesizedClaim(text="Rebuilt the pipeline", support=["Built on Kubernetes"]),
        ],
        tech=["Terraform"],  # not in _DECK — must never survive verification
    )
    synthesis = _SeqAgent([SynthesizedFragment(entries=[entry])])

    fragment, drops = synthesize_document(
        _doc(), _DECK, profile_skeleton(_facts()), synthesis, _approve_all()
    )

    assert any("Terraform" in d for d in drops)
    assert fragment.entries, "the sibling claim should have kept the entry alive"

    facts, _ = fragment_to_facts(_doc(), fragment, profile_skeleton(_facts()))
    stub = facts.experience[0]
    assert "Terraform" not in stub.tech
