from pathlib import Path

import pytest

from resume_agent.config import Settings
from resume_agent.settings_sections import (
    SECTIONS_BY_ID,
    SETTINGS_SECTIONS,
    arcname_for,
    default_path,
    live_paths,
    section_for,
)
from resume_agent.tenancy.context import UserContext, use_context
from resume_agent.tenancy.workspace import WorkspacePaths


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
        "resume_agent.db",
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
