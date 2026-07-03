"""Craft blocks: fact-lock-safe wording and per-role targeting."""

from resume_agent.tailor.craft import CRAFT_MATCH_PLAN, CRAFT_REVIEWERS, CRAFT_WRITER

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
            assert fragment not in lowered, f"{fragment!r} found in: {line}"


def test_fact_check_gate_has_no_craft_block():
    assert "fact-check" not in CRAFT_REVIEWERS
