import io
import json
import tarfile
from pathlib import Path

import pytest

from resume_agent.config import Settings
from resume_agent.services.settings_bundle import (
    BUNDLE_VERSION,
    MANIFEST_NAME,
    InvalidBundleError,
    UnsupportedBundleVersionError,
    export_settings_bundle,
    read_bundle_manifest,
    validate_member,
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


def write_bundle(tmp_path: Path, manifest_body: object, files: dict[str, str]) -> Path:
    archive = tmp_path / "bundle.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        if manifest_body is not None:
            blob = json.dumps(manifest_body).encode("utf-8")
            info = tarfile.TarInfo(MANIFEST_NAME)
            info.size = len(blob)
            tar.addfile(info, io.BytesIO(blob))
        for name, text in files.items():
            blob = text.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(blob)
            tar.addfile(info, io.BytesIO(blob))
    return archive


def test_read_manifest_separates_known_from_unknown_sections(tmp_path):
    archive = write_bundle(
        tmp_path,
        {
            "version": 1,
            "exportedAt": "2026-07-23T00:00:00+00:00",
            "sections": ["sources", "from_the_future"],
        },
        {"config/connectors.yaml": "companies: []\n"},
    )
    parsed = read_bundle_manifest(archive)
    assert parsed.sections == ("sources",)
    assert parsed.unknown_sections == ("from_the_future",)


def test_read_manifest_rejects_a_missing_manifest(tmp_path):
    archive = write_bundle(tmp_path, None, {"config/connectors.yaml": "x: 1\n"})
    with pytest.raises(InvalidBundleError):
        read_bundle_manifest(archive)


def test_read_manifest_rejects_an_unknown_version(tmp_path):
    archive = write_bundle(
        tmp_path, {"version": 99, "exportedAt": "", "sections": []}, {}
    )
    with pytest.raises(UnsupportedBundleVersionError):
        read_bundle_manifest(archive)


def test_read_manifest_rejects_a_non_tar_upload(tmp_path):
    archive = tmp_path / "not-a-bundle.tar.gz"
    archive.write_bytes(b"this is not gzip")
    with pytest.raises(InvalidBundleError):
        read_bundle_manifest(archive)


@pytest.mark.parametrize(
    ("arcname", "body"),
    [
        ("config/connectors.yaml", "companies: [\n"),
        ("config/search.yaml", ": : :\n"),
        ("data/profile/overrides.yaml", "ban: {oops\n"),
        ("data/profile/group_corrections.json", "{not json"),
        ("data/taxonomy/taxonomy_corrections.json", "{not json"),
    ],
)
def test_validate_member_rejects_corruption(tmp_path, arcname, body):
    staged = tmp_path / "staged"
    staged.write_text(body, encoding="utf-8")
    with pytest.raises(InvalidBundleError):
        validate_member(arcname, staged)


def test_validate_member_rejects_a_traversing_template_stem(tmp_path):
    staged = tmp_path / "staged.typ"
    staged.write_text("#let x = 1", encoding="utf-8")
    with pytest.raises(InvalidBundleError):
        validate_member("config/templates/../evil.typ", staged)


def test_validate_member_accepts_a_ledger_naming_unknown_clusters(tmp_path):
    staged = tmp_path / "staged.json"
    staged.write_text(
        json.dumps({"domain_renames": {"cluster-i-do-not-have": "whatever"}}),
        encoding="utf-8",
    )
    validate_member("data/taxonomy/taxonomy_corrections.json", staged)


def test_validate_member_accepts_valid_documents(tmp_path):
    staged = tmp_path / "staged.yaml"
    staged.write_text("titles: [engineer]\n", encoding="utf-8")
    validate_member("config/search.yaml", staged)


@pytest.mark.parametrize(
    ("arcname", "body"),
    [
        # match_plan_enabled exists on the real ReviewConfig domain model but
        # not on the API's wire-only ReviewConfigDoc. Pydantic's default
        # extra="ignore" means validating against the wrong model would let
        # this typo through silently -- it must fail here, at import, not on
        # the next tailor run.
        ("config/review.yaml", "match_plan_enabled: not-a-bool\n"),
        ("config/review_deep.yaml", "match_plan_enabled: not-a-bool\n"),
    ],
)
def test_validate_member_checks_fields_the_wire_schema_omits(tmp_path, arcname, body):
    staged = tmp_path / "staged.yaml"
    staged.write_text(body, encoding="utf-8")
    with pytest.raises(InvalidBundleError):
        validate_member(arcname, staged)
