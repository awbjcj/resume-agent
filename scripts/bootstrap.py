"""Idempotent, cross-platform development bootstrap for the repository."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def seed_local_config(root: Path = ROOT) -> list[Path]:
    """Create editable local files from examples without replacing user data."""
    created: list[Path] = []
    pairs = [(root / ".env.example", root / ".env")]
    pairs.extend(
        (example, example.with_name(example.name.removesuffix(".example")))
        for example in sorted((root / "config").glob("*.example"))
    )
    for source, target in pairs:
        if source.is_file() and not target.exists():
            shutil.copy2(source, target)
            created.append(target)
    return created


def require_tool(name: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        raise SystemExit(
            f"Required tool '{name}' was not found on PATH. "
            "Install it, open a new terminal, and run bootstrap again."
        )
    return executable


def bootstrap(*, browser: bool = False, root: Path = ROOT) -> None:
    uv = require_tool("uv")
    npm = require_tool("npm")
    created = seed_local_config(root)
    for path in created:
        print(f"Created {path.relative_to(root)}")
    subprocess.run([uv, "sync", "--locked"], cwd=root, check=True)
    subprocess.run([npm, "ci", "--prefix", "web"], cwd=root, check=True)
    if browser:
        subprocess.run(
            [uv, "run", "playwright", "install", "chromium"],
            cwd=root,
            check=True,
        )
    print("\nBootstrap complete. Start both apps with:")
    print("  uv run python scripts/dev.py")
    print("Then open http://localhost:5173")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--browser",
        action="store_true",
        help="also install Chromium for browser-backed job sources",
    )
    args = parser.parse_args()
    bootstrap(browser=args.browser)


if __name__ == "__main__":
    main()
