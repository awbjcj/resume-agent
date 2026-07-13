from pathlib import Path

from resume_agent.tenancy.local import rebase_cli_path
from resume_agent.config import Settings
from resume_agent.tenancy.context import UserContext, use_context
from resume_agent.tenancy.workspace import WorkspacePaths
from resume_agent.cli import _tenant_cli_path


def test_rebase_cli_path_maps_only_known_defaults():
    paths = WorkspacePaths(Path("root/users/alice"))
    assert (
        rebase_cli_path("data/profile/facts.json", paths)
        == paths.profile_dir / "facts.json"
    )
    assert (
        rebase_cli_path("config/search.yaml", paths) == paths.config_dir / "search.yaml"
    )
    explicit = Path("C:/custom/search.yaml")
    assert rebase_cli_path(explicit, paths) == explicit


def test_cli_filesystem_checks_use_the_active_workspace(tmp_path):
    paths = WorkspacePaths(tmp_path / "users" / "alice")
    context = UserContext(
        user_id="abc123def456",
        username="alice",
        role="user",
        paths=paths,
        settings=Settings(_env_file=None),  # type: ignore[call-arg]
        engine=None,
        system_engine=None,
        own_key_providers=frozenset(),
    )
    with use_context(context):
        resolved = _tenant_cli_path("data/profile/facts.json")
        assert resolved == paths.profile_dir / "facts.json"
        assert _tenant_cli_path(resolved) == resolved
