import json

from resume_tailor_harness.discovery.industry import (
    IndustryCandidate,
    IndustryClassification,
    IndustryGroup,
    classify_industries,
)


class _Result:
    def __init__(self, content):
        self.content = content


class _Runner:
    def __init__(self, content):
        self.content = content
        self.prompts: list[str] = []

    def run(self, prompt: str):
        self.prompts.append(prompt)
        return _Result(self.content)

    async def arun(self, prompt: str):
        return self.run(prompt)


def _candidate(company: str, industry: str) -> IndustryCandidate:
    return IndustryCandidate(company=company, industry=industry)


def test_classifier_reuses_existing_and_converges_same_batch_synonyms():
    candidates = [
        _candidate("stripe", "financial technology"),
        _candidate("waymo", "self driving cars"),
        _candidate("cruise", "autonomous vehicle technology"),
    ]
    runner = _Runner(
        IndustryClassification(
            groups=[
                IndustryGroup(canonical="Fintech", candidates=[candidates[0]]),
                IndustryGroup(
                    canonical="Autonomous Driving", candidates=candidates[1:]
                ),
            ]
        )
    )

    outcome = classify_industries(candidates, ["Fintech"], runner)

    assert outcome.assignments == {
        ("stripe", "financial technology"): "Fintech",
        ("waymo", "self driving cars"): "Autonomous Driving",
        ("cruise", "autonomous vehicle technology"): "Autonomous Driving",
    }
    payload = json.loads(runner.prompts[0])
    assert payload["existing_canonicals"] == ["Fintech"]
    assert payload["candidates"] == [
        {"company": "cruise", "industry": "autonomous vehicle technology"},
        {"company": "stripe", "industry": "financial technology"},
        {"company": "waymo", "industry": "self driving cars"},
    ]


def test_classifier_preserves_valid_partial_groups_and_rejects_conflicts():
    good = _candidate("stripe", "financial technology")
    conflict_a = _candidate("acme", "health tech")
    conflict_b = _candidate("acme", "medical software")
    missing = _candidate("unknown", "industrial automation")
    runner = _Runner(
        IndustryClassification(
            groups=[
                IndustryGroup(canonical="Fintech", candidates=[good]),
                IndustryGroup(canonical="Healthcare", candidates=[conflict_a]),
                IndustryGroup(canonical="Software", candidates=[conflict_b]),
                IndustryGroup(
                    canonical="Invented",
                    candidates=[_candidate("model company", "model label")],
                ),
            ]
        )
    )

    outcome = classify_industries(
        [good, conflict_a, conflict_b, missing], ["Fintech", "Healthcare"], runner
    )

    assert outcome.assignments == {("stripe", "financial technology"): "Fintech"}
    assert outcome.unresolved == {
        ("acme", "health tech"),
        ("acme", "medical software"),
        ("unknown", "industrial automation"),
    }


def test_classifier_collapses_trivial_variants_of_one_new_canonical():
    first = _candidate("waymo", "self driving cars")
    second = _candidate("cruise", "autonomous vehicles")
    runner = _Runner(
        IndustryClassification(
            groups=[
                IndustryGroup(canonical="Autonomous-Driving", candidates=[first]),
                IndustryGroup(canonical="Autonomous_Driving", candidates=[second]),
            ]
        )
    )

    outcome = classify_industries([first, second], [], runner)

    assert set(outcome.assignments.values()) == {"Autonomous-Driving"}


def test_classifier_rejects_one_alias_assigned_to_multiple_canonicals():
    first = _candidate("stripe", "fintech")
    second = _candidate("adyen", "fintech")
    runner = _Runner(
        IndustryClassification(
            groups=[
                IndustryGroup(canonical="Fintech", candidates=[first]),
                IndustryGroup(canonical="Banking", candidates=[second]),
            ]
        )
    )

    outcome = classify_industries([first, second], [], runner)

    assert outcome.assignments == {}
    assert outcome.unresolved == {("stripe", "fintech"), ("adyen", "fintech")}


def test_classifier_rejects_non_structured_output_without_fallback():
    candidate = _candidate("stripe", "fintech")

    outcome = classify_industries([candidate], [], _Runner("not structured"))

    assert outcome.assignments == {}
    assert outcome.unresolved == {("stripe", "fintech")}
