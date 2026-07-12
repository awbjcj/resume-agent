from pathlib import Path

from resume_agent.tenancy.local import rebase_cli_path
from resume_agent.tenancy.workspace import WorkspacePaths


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
