import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_EXAMPLES = (
    "search.yaml.example",
    "connectors.yaml.example",
    "profile_sources.yaml.example",
    "review.yaml.example",
    "review_deep.yaml.example",
    "render.yaml.example",
)


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    remedy: str = ""


def check_python(version: tuple[int, int, int] | None = None) -> CheckResult:
    major, minor, *_ = version or sys.version_info
    ok = (major, minor) >= (3, 13)
    return CheckResult(
        "python",
        ok,
        f"Python {major}.{minor}",
        remedy="" if ok else "Install Python 3.13+ (this project requires it).",
    )


def check_uv(which: Callable[[str], str | None] = shutil.which) -> CheckResult:
    found = which("uv") is not None
    return CheckResult(
        "uv",
        found,
        "uv found" if found else "uv not found",
        remedy="" if found else "Install uv: https://docs.astral.sh/uv/",
    )


def check_chromium(which: Callable[[str], str | None] = shutil.which) -> CheckResult:
    found = which("playwright") is not None
    return CheckResult(
        "chromium",
        found,
        "playwright available" if found else "playwright CLI not found",
        remedy="" if found else "Only needed for LinkedIn scrape: run 'uv run playwright install chromium'.",
    )


def check_examples_present(root: str | Path = ".") -> CheckResult:
    config = Path(root) / "config"
    missing = [name for name in _EXAMPLES if not (config / name).exists()]
    return CheckResult(
        "examples",
        not missing,
        "all example configs present" if not missing else f"missing: {', '.join(missing)}",
        remedy="" if not missing else "Re-clone the repo; config/*.example files are tracked.",
    )
