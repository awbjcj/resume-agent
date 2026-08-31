from resume_tailor_harness.tailor.style_guide import (
    STYLE_GUIDE_HEADER,
    compose_instructions,
    load_style_guide,
)


def test_compose_appends_style_beneath_base():
    base = ["Rewrite the resume.", "Never invent anything."]

    out = compose_instructions(base, "Write in a crisp consulting register.")

    assert out[:2] == ["Rewrite the resume.", "Never invent anything."]
    assert out[2] == STYLE_GUIDE_HEADER
    assert out[3] == "Write in a crisp consulting register."


def test_compose_is_noop_for_empty_guide():
    base = ["Rewrite the resume.", "Never invent anything."]

    assert compose_instructions(base, None) == base
    assert compose_instructions(base, "   \n  ") == base


def test_compose_does_not_mutate_base():
    base = ["only line"]

    compose_instructions(base, "some style")

    assert base == ["only line"]


def test_load_returns_stripped_text(tmp_path):
    f = tmp_path / "style.md"
    f.write_text(
        "\n  Lead every bullet with a quantified outcome.  \n", encoding="utf-8"
    )

    assert load_style_guide(f) == "Lead every bullet with a quantified outcome."


def test_load_missing_path_returns_none(tmp_path):
    assert load_style_guide(tmp_path / "nope.md") is None
    assert load_style_guide(None) is None


def test_load_empty_or_whitespace_file_returns_none(tmp_path):
    f = tmp_path / "empty.md"
    f.write_text("   \n  \n", encoding="utf-8")

    assert load_style_guide(f) is None
