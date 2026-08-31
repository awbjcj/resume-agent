from pathlib import Path
from types import SimpleNamespace

from evals.cl_runner import run_cl_case
from evals.judge import DimensionScore, JudgeVerdict
from evals.schema import load_case
from resume_tailor_harness.models.cover_letter import (
    CoverLetterContent,
    CoverLetterParagraph,
)
from resume_tailor_harness.models.profile import ProfileFacts


class _StubRunner:
    def __init__(self, contents):
        self._contents = list(contents)
        self.calls = 0
        self.prompts: list[str] = []

    def run(self, prompt):
        self.calls += 1
        self.prompts.append(prompt)
        return SimpleNamespace(content=self._contents.pop(0), metrics=None)

    async def arun(self, prompt):
        return self.run(prompt)


def _profile() -> ProfileFacts:
    return ProfileFacts.model_validate_json(
        Path("evals/profiles/backend_eng.json").read_text(encoding="utf-8")
    )


def _case():
    return load_case(Path("evals/cases/cl_case_02_adjacent_skill.json"))


def _verdict(rubric):
    return JudgeVerdict(
        output_quality=80,
        dimensions=[
            DimensionScore(dimension=dimension, score=80, rationale="r")
            for dimension in rubric
        ],
    )


def _letter(text: str, provenance: list[str]) -> CoverLetterContent:
    return CoverLetterContent(
        contact=_profile().contact,
        greeting="Dear team,",
        paragraphs=[CoverLetterParagraph(text=text, provenance=provenance)],
        closing="Sincerely",
    )


def test_clean_draft_needs_no_revision():
    case = _case()
    draft = _StubRunner([_letter("I build Python FastAPI services.", ["e1b1"])])
    reviser = _StubRunner([])
    judge = _StubRunner([_verdict(case.rubric)])

    result = run_cl_case(case, _profile(), draft, reviser, judge)

    assert result.revise_rounds == 0
    assert result.provenance_ok is True
    assert result.trap_ok is True
    assert result.final_quality == 80
    assert reviser.calls == 0


def test_bad_provenance_triggers_one_revise_round():
    case = _case()
    dirty = _letter("I build Python services.", ["not-a-real-fact-id"])
    clean = _letter("I build Python services.", ["e1b1"])

    result = run_cl_case(
        case,
        _profile(),
        _StubRunner([dirty]),
        _StubRunner([clean]),
        _StubRunner([_verdict(case.rubric)]),
    )

    assert result.revise_rounds == 1
    assert result.provenance_ok is True


def test_forbidden_term_fails_trap():
    case = _case()
    letter = _letter("I build production Flask services.", ["e1b1"])

    result = run_cl_case(
        case,
        _profile(),
        _StubRunner([letter]),
        _StubRunner([]),
        _StubRunner([_verdict(case.rubric)]),
    )

    assert result.trap_ok is False
    assert result.provenance_ok is True


def test_judge_receives_profile_and_house_style():
    case = _case()
    judge = _StubRunner([_verdict(case.rubric)])

    run_cl_case(
        case,
        _profile(),
        _StubRunner([_letter("I build Python services.", ["e1b1"])]),
        _StubRunner([]),
        judge,
        style_guide="Write crisply.",
    )

    assert "CANDIDATE PROFILE (JSON):" in judge.prompts[0]
    assert "Built and operated Python FastAPI services" in judge.prompts[0]
    assert "HOUSE STYLE:\nWrite crisply." in judge.prompts[0]
