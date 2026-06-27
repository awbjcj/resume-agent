import pytest

from resume_agent.tracking.canonicalize import (
    SkillThemes,
    ThemeGroup,
    build_skill_themer,
    themes_to_pairs,
)


def test_themes_to_pairs_returns_trimmed_exact_partition():
    themes = [
        ThemeGroup(label="  Backend  ", skills=[" python ", "django", "python"]),
        ThemeGroup(label="Data", skills=["postgresql"]),
    ]

    assert themes_to_pairs(themes, {"python", "django", "postgresql"}) == [
        ("Backend", ["python", "django"]),
        ("Data", ["postgresql"]),
    ]


def test_themes_to_pairs_rejects_unknown_and_missing_members():
    themes = [ThemeGroup(label="Backend", skills=["python", "rust"])]

    with pytest.raises(ValueError):
        themes_to_pairs(themes, {"python", "django"})


def test_themes_to_pairs_rejects_member_in_multiple_groups():
    themes = [
        ThemeGroup(label="Backend", skills=["python"]),
        ThemeGroup(label="Data", skills=["python", "postgresql"]),
    ]

    with pytest.raises(ValueError):
        themes_to_pairs(themes, {"python", "postgresql"})


def test_themes_to_pairs_rejects_blank_label():
    themes = [ThemeGroup(label="   ", skills=["python"])]

    with pytest.raises(ValueError):
        themes_to_pairs(themes, {"python"})


class _FakeResult:
    def __init__(self, content):
        self.content = content


class _FakeRunner:
    def __init__(self, themes):
        self._themes = themes

    def run(self, prompt):
        return _FakeResult(SkillThemes(themes=self._themes))

    async def arun(self, prompt):
        return self.run(prompt)


def test_skill_themer_uses_typed_response_from_injected_runner():
    themer = build_skill_themer(
        agent=_FakeRunner(
            [
                ThemeGroup(label="Backend", skills=["python", "django"]),
                ThemeGroup(label="Data", skills=["postgresql"]),
            ]
        )
    )

    assert themer({"python", "django", "postgresql"}) == [
        ("Backend", ["python", "django"]),
        ("Data", ["postgresql"]),
    ]


class _FailIfCalledRunner:
    def run(self, prompt):
        raise AssertionError("runner should not be called")

    async def arun(self, prompt):
        raise AssertionError("runner should not be called")


def test_skill_themer_short_circuits_empty_tokens():
    themer = build_skill_themer(agent=_FailIfCalledRunner())

    assert themer(set()) == []
