from pathlib import Path

import pytest

from resume_agent.deploy import prepare_data_root


def _require_symlinks(tmp_path: Path) -> None:
    probe = tmp_path / "probe"
    try:
        probe.symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    probe.unlink()


def _roots(tmp_path: Path):
    app_root = tmp_path / "app"
    app_root.mkdir()
    defaults = app_root / "config.defaults"
    defaults.mkdir()
    (defaults / "search.yaml").write_text("titles: []\n", encoding="utf-8")
    (defaults / "review.yaml.example").write_text("max_rounds: 2\n", encoding="utf-8")
    return app_root, app_root / "data", defaults


def test_fresh_boot_seeds_and_links_mutable_paths(tmp_path):
    _require_symlinks(tmp_path)
    app_root, data_root, defaults = _roots(tmp_path)

    prepare_data_root(app_root, data_root, defaults)

    assert (data_root / "config" / "search.yaml").read_text(
        encoding="utf-8"
    ) == "titles: []\n"
    assert (data_root / "config" / "review.yaml").read_text(
        encoding="utf-8"
    ) == "max_rounds: 2\n"
    assert (data_root / "output").is_dir()
    assert (data_root / ".env").is_file()
    assert all((app_root / name).is_symlink() for name in ("config", "output", ".env"))


def test_redeploy_preserves_data_and_is_idempotent(tmp_path):
    _require_symlinks(tmp_path)
    app_root, data_root, defaults = _roots(tmp_path)
    prepare_data_root(app_root, data_root, defaults)
    (data_root / "config" / "search.yaml").write_text(
        "titles: [edited]\n", encoding="utf-8"
    )
    (data_root / "config" / "review.yaml").write_text(
        "max_rounds: 9\n", encoding="utf-8"
    )
    (data_root / ".env").write_text("KEY=value\n", encoding="utf-8")

    prepare_data_root(app_root, data_root, defaults)

    assert "edited" in (data_root / "config" / "search.yaml").read_text(
        encoding="utf-8"
    )
    assert (data_root / "config" / "review.yaml").read_text(
        encoding="utf-8"
    ) == "max_rounds: 9\n"
    assert (data_root / ".env").read_text(encoding="utf-8") == "KEY=value\n"


def test_refuses_real_path_or_wrong_symlink_target(tmp_path):
    _require_symlinks(tmp_path)
    app_root, data_root, defaults = _roots(tmp_path)
    (app_root / "config").mkdir()
    with pytest.raises(RuntimeError, match="refusing to shadow"):
        prepare_data_root(app_root, data_root, defaults)

    (app_root / "config").rmdir()
    wrong = tmp_path / "wrong"
    wrong.mkdir()
    (app_root / "config").symlink_to(wrong, target_is_directory=True)
    with pytest.raises(RuntimeError, match="wrong target"):
        prepare_data_root(app_root, data_root, defaults)
