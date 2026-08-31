from pathlib import Path

import pytest

from resume_tailor_harness.config import Settings
from resume_tailor_harness.settings_sections import (
    SECTIONS_BY_ID,
    SETTINGS_SECTIONS,
    arcname_for,
    default_path,
    is_customized,
    live_paths,
    reset_section,
    section_for,
)
from resume_tailor_harness.tenancy.context import UserContext, use_context
from resume_tailor_harness.tenancy.workspace import WorkspacePaths


def _context(paths: WorkspacePaths) -> UserContext:
    """UserContext has eight required fields and is_admin is a property, not
    one of them. This mirrors the helper in tests/tenancy/test_workspace.py."""
    return UserContext(
        user_id="u1",
        username="u1",
        role="user",
        paths=paths,
        settings=Settings(_env_file=None),  # type: ignore[call-arg]
        engine=None,
        system_engine=None,
        own_key_providers=frozenset(),
    )


EXPECTED_IDS = (
    "sources",
    "search",
    "review",
    "agent_guidance",
    "style_guide",
    "render",
    "templates",
    "prune",
    "profile_sources",
    "skill_overrides",
    "skill_groups",
    "taxonomy",
)


def test_registry_declares_twelve_sections_in_order():
    assert tuple(section.id for section in SETTINGS_SECTIONS) == EXPECTED_IDS


def test_registry_never_names_a_credential():
    forbidden = {
        "secrets.env",
        "gmail_token.json",
        "resume_tailor_harness.db",
        "config/gmail_credentials.json",
    }
    named = {entry for section in SETTINGS_SECTIONS for entry in section.files}
    assert named.isdisjoint(forbidden)


def test_section_for_returns_none_for_unknown_id():
    assert section_for("nope") is None
    assert section_for("sources") is SECTIONS_BY_ID["sources"]


def test_live_paths_resolves_into_the_active_workspace(tmp_path):
    paths = WorkspacePaths(tmp_path / "users" / "u1")
    target = paths.config_dir / "connectors.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("companies: []\n", encoding="utf-8")
    with use_context(_context(paths)):
        assert live_paths("config/connectors.yaml") == [target]


def test_live_paths_is_empty_when_the_file_is_absent(tmp_path):
    paths = WorkspacePaths(tmp_path / "users" / "u1")
    with use_context(_context(paths)):
        assert live_paths("config/connectors.yaml") == []


def test_live_paths_expands_a_glob_entry(tmp_path):
    paths = WorkspacePaths(tmp_path / "users" / "u1")
    directory = paths.config_dir / "templates"
    directory.mkdir(parents=True)
    (directory / "b.typ").write_text("#b", encoding="utf-8")
    (directory / "a.typ").write_text("#a", encoding="utf-8")
    (directory / "notes.txt").write_text("ignored", encoding="utf-8")
    with use_context(_context(paths)):
        found = live_paths("config/templates/*.typ")
    assert [path.name for path in found] == ["a.typ", "b.typ"]


def test_default_path_finds_the_shipped_example():
    found = default_path("config/connectors.yaml")
    assert found is not None
    assert found.name == "connectors.yaml.example"
    assert found.is_file()


def test_default_path_is_none_for_sections_that_ship_no_example():
    assert default_path("config/agent_guidance.yaml") is None
    assert default_path("data/profile/overrides.yaml") is None
    assert default_path("data/profile/group_corrections.json") is None
    assert default_path("data/taxonomy/taxonomy_corrections.json") is None
    assert default_path("config/templates/*.typ") is None


@pytest.mark.parametrize(
    ("entry", "filename", "expected"),
    [
        ("config/connectors.yaml", "connectors.yaml", "config/connectors.yaml"),
        ("config/templates/*.typ", "mine.typ", "config/templates/mine.typ"),
    ],
)
def test_arcname_for_is_posix_and_glob_aware(entry, filename, expected):
    assert arcname_for(entry, Path("/anywhere") / filename) == expected


def _workspace(tmp_path):
    paths = WorkspacePaths(tmp_path / "users" / "u1")
    paths.config_dir.mkdir(parents=True)
    return paths, _context(paths)


def test_absent_defaulted_file_is_not_customized(tmp_path):
    _, context = _workspace(tmp_path)
    with use_context(context):
        assert is_customized(SECTIONS_BY_ID["sources"]) is False


def test_file_matching_the_example_is_not_customized(tmp_path):
    paths, context = _workspace(tmp_path)
    example = default_path("config/connectors.yaml")
    assert example is not None
    (paths.config_dir / "connectors.yaml").write_bytes(example.read_bytes())
    with use_context(context):
        assert is_customized(SECTIONS_BY_ID["sources"]) is False


def test_file_differing_from_the_example_is_customized(tmp_path):
    paths, context = _workspace(tmp_path)
    (paths.config_dir / "connectors.yaml").write_text("companies: []\n", "utf-8")
    with use_context(context):
        assert is_customized(SECTIONS_BY_ID["sources"]) is True


def test_section_with_no_example_is_customized_when_the_file_exists(tmp_path):
    paths, context = _workspace(tmp_path)
    with use_context(context):
        assert is_customized(SECTIONS_BY_ID["agent_guidance"]) is False
    (paths.config_dir / "agent_guidance.yaml").write_text("writer: hi\n", "utf-8")
    with use_context(context):
        assert is_customized(SECTIONS_BY_ID["agent_guidance"]) is True


def test_reset_restores_the_shipped_example(tmp_path):
    paths, context = _workspace(tmp_path)
    target = paths.config_dir / "connectors.yaml"
    target.write_text("companies: []\n", encoding="utf-8")
    example = default_path("config/connectors.yaml")
    assert example is not None
    with use_context(context):
        reset_section(SECTIONS_BY_ID["sources"])
    assert target.read_bytes() == example.read_bytes()


def test_reset_deletes_when_no_example_ships(tmp_path):
    paths, context = _workspace(tmp_path)
    target = paths.config_dir / "agent_guidance.yaml"
    target.write_text("writer: hi\n", encoding="utf-8")
    with use_context(context):
        reset_section(SECTIONS_BY_ID["agent_guidance"])
    assert not target.exists()


def test_reset_clears_the_templates_directory(tmp_path):
    paths, context = _workspace(tmp_path)
    directory = paths.config_dir / "templates"
    directory.mkdir()
    (directory / "mine.typ").write_text("#mine", encoding="utf-8")
    (directory / "keep.txt").write_text("not a template", encoding="utf-8")
    with use_context(context):
        reset_section(SECTIONS_BY_ID["templates"])
    assert not (directory / "mine.typ").exists()
    assert (directory / "keep.txt").exists()


def test_reset_of_an_absent_section_is_a_noop(tmp_path):
    _, context = _workspace(tmp_path)
    with use_context(context):
        reset_section(SECTIONS_BY_ID["taxonomy"])  # must not raise


def test_every_section_resets_without_error(tmp_path):
    _, context = _workspace(tmp_path)
    with use_context(context):
        for section in SETTINGS_SECTIONS:
            reset_section(section)
            assert is_customized(section) is False
