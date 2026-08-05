"""Craft blocks: fact-lock-safe wording and per-role targeting."""

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


def _all_craft_lines() -> list[str]:
    return [
        *CRAFT_WRITER,
        *CRAFT_MATCH_PLAN,
        *(line for block in CRAFT_REVIEWERS.values() for line in block),
    ]


def test_craft_blocks_are_nonempty():
    assert CRAFT_WRITER
    assert CRAFT_MATCH_PLAN
    assert set(CRAFT_REVIEWERS) == SCORED_CRAFT_REVIEWERS
    assert all(block for block in CRAFT_REVIEWERS.values())


def test_craft_lines_avoid_fabrication_language():
    for line in _all_craft_lines():
        lowered = line.lower()
        for fragment in FABRICATION_FRAGMENTS:
            if fragment == "invent" and "inventing an outcome to fill the gap fails" in lowered:
                continue
            assert fragment not in lowered, f"{fragment!r} found in: {line}"


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
    assert "must-have coverage" in text
    assert "gap" in text
