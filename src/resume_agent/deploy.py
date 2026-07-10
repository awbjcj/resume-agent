"""Prepare the single mounted data root before the container starts."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

LINKS: dict[str, str] = {"output": "output", "config": "config", ".env": ".env"}


def prepare_data_root(
    app_root: Path,
    data_root: Path,
    defaults_dir: Path | None = None,
) -> None:
    data_root.mkdir(parents=True, exist_ok=True)
    config_target = data_root / "config"
    if defaults_dir is not None and defaults_dir.is_dir() and not config_target.exists():
        shutil.copytree(defaults_dir, config_target)
    config_target.mkdir(exist_ok=True)
    (data_root / "output").mkdir(exist_ok=True)
    (data_root / ".env").touch(exist_ok=True)

    for name, relative_target in LINKS.items():
        link = app_root / name
        target = data_root / relative_target
        if link.is_symlink():
            if link.resolve(strict=False) != target.resolve(strict=False):
                raise RuntimeError(
                    f"{link} points to the wrong target; expected {target}"
                )
            continue
        if link.exists():
            raise RuntimeError(
                f"{link} already exists and is not a symlink; refusing to shadow it"
            )
        link.symlink_to(target, target_is_directory=target.is_dir())


def main() -> None:
    app_root = Path(os.environ.get("APP_ROOT", "/app"))
    data_root = Path(os.environ.get("DATA_ROOT", str(app_root / "data")))
    prepare_data_root(app_root, data_root, app_root / "config.defaults")


if __name__ == "__main__":
    main()
