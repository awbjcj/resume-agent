import pytest

from resume_agent.tracking.canonicalize import (
    SkillThemes,
    ThemeGroup,
    build_skill_themer,
    themes_to_pairs,
)


def test_themes_to_pairs_returns_trimmed_exact_partition():
    themes = [
        ThemeGroup(label="  Backend  ", skills=[" python ", "django"]),
        ThemeGroup(label="Data", skills=["postgresql"]),
    ]

    assert themes_to_pairs(themes, {"python", "django", "postgresql"}) == [
        ("Backend", ["python", "django"]),
        ("Data", ["postgresql"]),
    ]


def test_themes_to_pairs_drops_unknown_member_and_backfills_missing():
    # "rust" is not an input token (model invented/rewrote it): drop it. The real
    # token it failed to place ("django") lands in the catch-all, never aborting.
    themes = [ThemeGroup(label="Backend", skills=["python", "rust"])]

    assert themes_to_pairs(themes, {"python", "django"}) == [
        ("Backend", ["python"]),
        ("Other", ["django"]),
    ]


def test_themes_to_pairs_projects_rewritten_member_onto_input():
    themes = [ThemeGroup(label="DevOps", skills=["CI/CD"])]

    assert themes_to_pairs(themes, {"ci cd"}) == [("DevOps", ["ci cd"])]


def test_themes_to_pairs_collects_dropped_tokens_into_catch_all():
    themes = [ThemeGroup(label="Backend", skills=["python"])]

    assert themes_to_pairs(themes, {"python", "retool", "ascii"}) == [
        ("Backend", ["python"]),
        ("Other", ["ascii", "retool"]),
    ]


def test_themes_to_pairs_extends_existing_catch_all_with_dropped_tokens():
    themes = [
        ThemeGroup(label="Backend", skills=["python"]),
        ThemeGroup(label="Other", skills=["bash"]),
    ]

    assert themes_to_pairs(themes, {"python", "bash", "ascii"}) == [
        ("Backend", ["python"]),
        ("Other", ["bash", "ascii"]),
    ]


def test_themes_to_pairs_drops_duplicate_member_in_same_group():
    themes = [ThemeGroup(label="Backend", skills=["python", " python "])]

    assert themes_to_pairs(themes, {"python"}) == [("Backend", ["python"])]


def test_themes_to_pairs_rejects_blank_skill_member():
    themes = [ThemeGroup(label="Backend", skills=["python", "   "])]

    with pytest.raises(ValueError):
        themes_to_pairs(themes, {"python"})


def test_themes_to_pairs_keeps_first_occurrence_across_groups():
    themes = [
        ThemeGroup(label="Backend", skills=["python"]),
        ThemeGroup(label="Data", skills=["python", "postgresql"]),
    ]

    assert themes_to_pairs(themes, {"python", "postgresql"}) == [
        ("Backend", ["python"]),
        ("Data", ["postgresql"]),
    ]


def test_themes_to_pairs_drops_theme_left_empty_after_dedup():
    themes = [
        ThemeGroup(label="Data", skills=["weaviate", "postgresql"]),
        ThemeGroup(label="AI", skills=["weaviate"]),
    ]

    assert themes_to_pairs(themes, {"weaviate", "postgresql"}) == [
        ("Data", ["weaviate", "postgresql"]),
    ]


def test_themes_to_pairs_merges_colliding_labels_under_first_label():
    themes = [
        ThemeGroup(label="Data & AI", skills=["weaviate"]),
        ThemeGroup(label="data ai", skills=["postgresql", "weaviate"]),
    ]

    assert themes_to_pairs(themes, {"weaviate", "postgresql"}) == [
        ("Data & AI", ["weaviate", "postgresql"]),
    ]


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


def test_skill_themer_repairs_token_assigned_to_multiple_themes():
    # Mirrors the production failure: the cheap model puts an ambiguous token
    # (a vector DB) in two themes. Keep-first repair must not abort the refresh.
    themer = build_skill_themer(
        agent=_FakeRunner(
            [
                ThemeGroup(label="Data", skills=["weaviate", "postgresql"]),
                ThemeGroup(label="AI", skills=["weaviate"]),
            ]
        )
    )

    assert themer({"weaviate", "postgresql"}) == [
        ("Data", ["weaviate", "postgresql"]),
    ]


def test_skill_themer_repairs_dropped_tokens_into_catch_all():
    # Mirrors the production failure: the cheap model omits niche tokens from
    # every theme. The dropped tokens must survive under a catch-all instead of
    # aborting the whole refresh.
    themer = build_skill_themer(
        agent=_FakeRunner(
            [
                ThemeGroup(label="ML", skills=["program induction"]),
                ThemeGroup(label="Tooling", skills=["retool"]),
            ]
        )
    )

    assert themer(
        {"program induction", "retool", "ascii", "simulation validation"}
    ) == [
        ("ML", ["program induction"]),
        ("Tooling", ["retool"]),
        ("Other", ["ascii", "simulation validation"]),
    ]


class _FailIfCalledRunner:
    def run(self, prompt):
        raise AssertionError("runner should not be called")

    async def arun(self, prompt):
        raise AssertionError("runner should not be called")


def test_skill_themer_short_circuits_empty_tokens():
    themer = build_skill_themer(agent=_FailIfCalledRunner())

    assert themer(set()) == []
