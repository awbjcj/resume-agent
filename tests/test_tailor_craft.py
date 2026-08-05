"""Craft blocks: fact-lock-safe wording and per-role targeting."""

import pytest

from resume_agent.tailor.agents import (
    _REVISER_INSTRUCTIONS,
    _REVISION_INSTRUCTIONS,
    _TAILOR_INSTRUCTIONS,
    _reviewer_instructions,
    _writer_instructions,
)
from resume_agent.tailor.craft import CRAFT_MATCH_PLAN, CRAFT_REVIEWERS, CRAFT_WRITER
from resume_agent.tailor.match_plan import _MATCH_PLAN_INSTRUCTIONS, _plan_instructions
from resume_agent.tailor.style_guide import STYLE_GUIDE_HEADER, compose_instructions

FABRICATION_FRAGMENTS = [
    "estimat",
    "assume",
    "approximat",
    "guess",
    "extrapolat",
    "fabricat",
    "plausible",
    "invent",
]

SCORED_CRAFT_REVIEWERS = {"ats-keyword", "recruiter", "hiring-manager", "concision"}
_ALLOWED_NEGATIVE_PHRASE = "inventing an outcome to fill the gap fails"


def _all_craft_lines() -> list[str]:
    return [
        *CRAFT_WRITER,
        *CRAFT_MATCH_PLAN,
        *(line for block in CRAFT_REVIEWERS.values() for line in block),
    ]


def _assert_no_fabrication_language(line: str) -> None:
    """Reject fabrication guidance while allowing the explicit prohibition."""
    lowered = line.lower().replace(_ALLOWED_NEGATIVE_PHRASE, "")
    for fragment in FABRICATION_FRAGMENTS:
        assert fragment not in lowered, f"{fragment!r} found in: {line}"


def test_craft_blocks_are_nonempty():
    assert CRAFT_WRITER
    assert CRAFT_MATCH_PLAN
    assert set(CRAFT_REVIEWERS) == SCORED_CRAFT_REVIEWERS
    assert all(block for block in CRAFT_REVIEWERS.values())


def test_craft_lines_avoid_fabrication_language():
    for line in _all_craft_lines():
        _assert_no_fabrication_language(line)


def test_fabrication_guard_rejects_an_authorizing_suffix():
    with pytest.raises(AssertionError):
        _assert_no_fabrication_language(
            f"{_ALLOWED_NEGATIVE_PHRASE}; inventing an outcome is allowed."
        )


def test_fact_check_gate_has_no_craft_block():
    assert "fact-check" not in CRAFT_REVIEWERS


def test_writer_instructions_keep_integrity_first():
    for base in (_TAILOR_INSTRUCTIONS, _REVISER_INSTRUCTIONS):
        out = _writer_instructions(base)
        assert out[: len(base)] == base
        assert out[len(base):] == CRAFT_WRITER


def test_style_guide_lands_after_craft():
    composed = compose_instructions(
        _writer_instructions(_TAILOR_INSTRUCTIONS), "house style"
    )
    assert composed.index(STYLE_GUIDE_HEADER) > composed.index(CRAFT_WRITER[-1])


def test_scored_reviewers_receive_their_craft_block():
    for name in SCORED_CRAFT_REVIEWERS:
        rendered = _reviewer_instructions(name)
        for line in CRAFT_REVIEWERS[name]:
            assert line in rendered


def test_fact_check_composition_is_craft_free():
    rendered = set(_reviewer_instructions("fact-check"))
    assert rendered.isdisjoint(set(_all_craft_lines()))


def test_revision_agent_stays_craft_free():
    assert set(_REVISION_INSTRUCTIONS).isdisjoint(set(CRAFT_WRITER))


def test_match_plan_instructions_keep_integrity_first():
    out = _plan_instructions()
    assert out[: len(_MATCH_PLAN_INSTRUCTIONS)] == _MATCH_PLAN_INSTRUCTIONS
    assert out[len(_MATCH_PLAN_INSTRUCTIONS):] == CRAFT_MATCH_PLAN


def test_ats_keyword_rubric_treats_coverage_as_authoritative():
    text = " ".join(CRAFT_REVIEWERS["ats-keyword"]).lower()
    assert "when must-have coverage is present it is authoritative" in text
    assert "marked 'gap' is a qualification the candidate genuinely lacks" in text
    assert "never score it as a missing keyword and never suggest adding it" in text
    assert "coverage only over requirements marked 'covered'" in text
    assert (
        "one marked 'adjacent' as emphasis material that may never be named as the job's own term"
        in text
    )


def test_writer_no_number_craft_branch_forbids_filling_the_gap():
    text = " ".join(CRAFT_WRITER).lower()
    assert (
        "when the cited facts carry no number, lead with the concrete action, its scope, "
        "and the specific systems involved"
    ) in text
    assert "that is a complete accomplishment bullet, not a lesser one" in text
    assert "inventing an outcome to fill the gap fails the round" in text
