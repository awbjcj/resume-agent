import json
import tarfile
from pathlib import Path

from resume_agent.config import Settings
from resume_agent.services.settings_bundle import (
    BUNDLE_VERSION,
    MANIFEST_NAME,
    export_settings_bundle,
)
from resume_agent.tenancy.context import UserContext, use_context
from resume_agent.tenancy.workspace import WorkspacePaths


def workspace(tmp_path):
    paths = WorkspacePaths(tmp_path / "users" / "u1")
    paths.config_dir.mkdir(parents=True)
    context = UserContext(
        user_id="u1",
        username="u1",
        role="user",
        paths=paths,
        settings=Settings(_env_file=None),  # type: ignore[call-arg]
        engine=None,
        system_engine=None,
        own_key_providers=frozenset(),
    )
    return paths, context


def members(archive: Path) -> set[str]:
    with tarfile.open(archive, "r:gz") as tar:
        return {member.name for member in tar.getmembers() if member.isfile()}


def manifest(archive: Path) -> dict:
    with tarfile.open(archive, "r:gz") as tar:
        handle = tar.extractfile(MANIFEST_NAME)
        assert handle is not None
        return json.loads(handle.read().decode("utf-8"))


def test_export_contains_only_populated_sections(tmp_path):
    paths, context = workspace(tmp_path)
    (paths.config_dir / "connectors.yaml").write_text("companies: []\n", "utf-8")
    with use_context(context):
        archive = export_settings_bundle(tmp_path / "out")

    assert members(archive) == {MANIFEST_NAME, "config/connectors.yaml"}
    parsed = manifest(archive)
    assert parsed["version"] == BUNDLE_VERSION
    assert parsed["sections"] == ["sources"]
    assert parsed["exportedAt"]


def test_export_carries_the_correction_ledgers(tmp_path):
    paths, context = workspace(tmp_path)
    (paths.root / "profile").mkdir(parents=True)
    (paths.root / "taxonomy").mkdir(parents=True)
    (paths.root / "profile" / "overrides.yaml").write_text("ban: [x]\n", "utf-8")
    (paths.root / "profile" / "group_corrections.json").write_text(
        '{"corrections": {}}', "utf-8"
    )
    (paths.root / "taxonomy" / "taxonomy_corrections.json").write_text(
        '{"aliases": {}}', "utf-8"
    )
    with use_context(context):
        archive = export_settings_bundle(tmp_path / "out")

    assert "data/profile/overrides.yaml" in members(archive)
    assert "data/profile/group_corrections.json" in members(archive)
    assert "data/taxonomy/taxonomy_corrections.json" in members(archive)
    assert set(manifest(archive)["sections"]) == {
        "skill_overrides",
        "skill_groups",
        "taxonomy",
    }


def test_export_never_carries_a_credential(tmp_path):
    paths, context = workspace(tmp_path)
    (paths.config_dir / "connectors.yaml").write_text("companies: []\n", "utf-8")
    (paths.config_dir / "gmail_credentials.json").write_text('{"web":{}}', "utf-8")
    paths.secrets_env.write_text("ANTHROPIC_API_KEY=sk-secret\n", encoding="utf-8")
    paths.gmail_token.write_text('{"token": "secret"}', encoding="utf-8")
    paths.db_file.write_bytes(b"SQLite format 3\x00")
    with use_context(context):
        archive = export_settings_bundle(tmp_path / "out")

    found = members(archive)
    assert found == {MANIFEST_NAME, "config/connectors.yaml"}
    blob = Path(archive).read_bytes()
    assert b"sk-secret" not in blob


def test_export_of_an_untouched_workspace_lists_no_sections(tmp_path):
    _, context = workspace(tmp_path)
    with use_context(context):
        archive = export_settings_bundle(tmp_path / "out")
    assert manifest(archive)["sections"] == []
    assert members(archive) == {MANIFEST_NAME}


def test_export_names_glob_members_by_their_real_filename(tmp_path):
    paths, context = workspace(tmp_path)
    directory = paths.config_dir / "templates"
    directory.mkdir()
    (directory / "mine.typ").write_text("#mine", encoding="utf-8")
    with use_context(context):
        archive = export_settings_bundle(tmp_path / "out")
    assert "config/templates/mine.typ" in members(archive)
