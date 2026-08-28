from resume_agent.config import Settings
from resume_agent.discovery.connectors.telemetry import read_runs, record_run
from resume_agent.settings_sections import seedable_entries
from resume_agent.taxonomy.skills import load_aliases
from resume_agent.tenancy.context import UserContext, use_context
from resume_agent.tenancy.workspace import (
    WorkspacePaths,
    effective_settings,
    provision_workspace,
    workspace_paths,
)


def _context(tmp_path):
    return UserContext(
        user_id="abc123def456",
        username="alice",
        role="user",
        paths=WorkspacePaths(tmp_path / "users" / "alice"),
        settings=Settings(_env_file=None),  # type: ignore[call-arg]
        engine=None,
        system_engine=None,
        own_key_providers=frozenset(),
    )


def test_record_run_lands_in_the_active_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    context = _context(tmp_path)
    with use_context(context):
        record_run("data/connector_runs.json", "greenhouse", added=3, error=None)
        assert read_runs("data/connector_runs.json")["greenhouse"]["added"] == 3
    telemetry_file = context.paths.root / "connector_runs.json"
    assert telemetry_file.exists()


def test_load_aliases_resolves_the_active_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    context = _context(tmp_path)
    aliases_file = context.paths.root / "skill_aliases.json"
    aliases_file.parent.mkdir(parents=True, exist_ok=True)
    aliases_file.write_text('{"reactjs": "react"}', encoding="utf-8")
    with use_context(context):
        assert load_aliases("data/skill_aliases.json") == {"reactjs": "react"}


def test_workspace_paths_include_all_tenant_roots(tmp_path):
    paths = workspace_paths(tmp_path, "abc123def456")
    assert paths.root == tmp_path / "users" / "abc123def456"
    assert paths.db_url == f"sqlite:///{paths.db_file.as_posix()}"
    assert paths.profile_dir == paths.root / "profile"
    assert paths.config_dir == paths.root / "config"
    assert paths.secrets_env == paths.root / "secrets.env"
    assert paths.runs_root == paths.root / "runs"


def test_provision_copies_every_example_without_overwriting(tmp_path):
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "search.yaml.example").write_text("first\n", encoding="utf-8")
    (templates / "render.yaml.example").write_text("render\n", encoding="utf-8")
    (templates / "style_guide.md.example").write_text("style\n", encoding="utf-8")

    paths = provision_workspace(
        tmp_path / "data", "abc123def456", template_dir=templates
    )
    assert (paths.config_dir / "search.yaml").read_text(encoding="utf-8") == "first\n"
    assert (paths.config_dir / "render.yaml").is_file()
    assert (paths.config_dir / "style_guide.md").is_file()
    (paths.config_dir / "search.yaml").write_text("edited\n", encoding="utf-8")
    provision_workspace(tmp_path / "data", "abc123def456", template_dir=templates)
    assert (paths.config_dir / "search.yaml").read_text(encoding="utf-8") == "edited\n"


def test_effective_settings_tracks_user_owned_provider_keys(tmp_path):
    paths = provision_workspace(tmp_path, "abc123def456", template_dir=tmp_path)
    paths.secrets_env.write_text(
        "ANTHROPIC_API_KEY=user-anthropic\n"
        "GITHUB_TOKEN=user-github\n"
        "MID_REASONING_EFFORT=low\n"
        "ANTHROPIC_BASE_URL=https://attacker.example\n"
        "OPENAI_BASE_URL=https://attacker.example/v1\n"
        "SESSION_SECRET=attacker\n"
        "DB_URL=sqlite:///attacker.db\n",
        encoding="utf-8",
    )
    base = Settings(
        _env_file=None,  # type: ignore[call-arg]
        anthropic_api_key="server-anthropic",
        anthropic_base_url="https://api.anthropic.com",
        openai_base_url="https://api.openai.com/v1",
        session_secret="platform-secret",
    )
    overlay = effective_settings(base, paths)
    assert overlay.settings.anthropic_api_key == "user-anthropic"
    assert overlay.settings.github_token == "user-github"
    assert overlay.settings.mid_reasoning_effort == "low"
    assert overlay.settings.anthropic_base_url == "https://api.anthropic.com"
    assert overlay.settings.openai_base_url == "https://api.openai.com/v1"
    assert overlay.settings.session_secret == "platform-secret"
    assert overlay.settings.db_url == paths.db_url
    assert overlay.own_key_providers == frozenset({"anthropic"})
    assert overlay.user_provider_keys == {"anthropic": "user-anthropic"}


def test_seedable_entries_are_config_files_that_ship_an_example():
    entries = seedable_entries()
    assert "config/connectors.yaml" in entries
    assert "config/search.yaml" in entries
    assert "config/agent_guidance.yaml" not in entries
    assert "data/profile/overrides.yaml" not in entries
    assert "config/templates/*.typ" not in entries


def test_provisioning_seeds_every_registry_default(tmp_path):
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "connectors.yaml.example").write_text("companies: []\n", "utf-8")
    (templates / "search.yaml.example").write_text("titles: []\n", "utf-8")
    (templates / "unlisted.yaml.example").write_text("nope: true\n", "utf-8")

    paths = provision_workspace(tmp_path / "data", "u1", template_dir=templates)

    assert (paths.config_dir / "connectors.yaml").read_text(
        "utf-8"
    ) == "companies: []\n"
    assert (paths.config_dir / "search.yaml").read_text("utf-8") == "titles: []\n"
    # Not in the registry, so provisioning no longer copies it.
    assert not (paths.config_dir / "unlisted.yaml").exists()


def test_provisioning_never_overwrites_an_existing_file(tmp_path):
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "search.yaml.example").write_text("titles: []\n", "utf-8")
    paths = provision_workspace(tmp_path / "data", "u1", template_dir=templates)
    (paths.config_dir / "search.yaml").write_text("titles: [dev]\n", "utf-8")

    provision_workspace(tmp_path / "data", "u1", template_dir=templates)

    assert (paths.config_dir / "search.yaml").read_text("utf-8") == "titles: [dev]\n"
