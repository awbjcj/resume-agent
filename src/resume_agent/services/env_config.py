"""Read/merge-write .env through the TUI wizard's pure helpers.

The one write path for web-managed env values. After a write, the cached
Settings singleton is cleared so run workers (which call get_settings() at
call time) see fresh values; the router additionally refreshes
app.state.settings for request-scoped dependencies.
"""

from __future__ import annotations

import os
from pathlib import Path

from resume_agent.config import Settings, get_settings
from resume_agent.setup.env_writer import format_env, merge_env, parse_env

DEFAULT_ENV_PATH = Path(".env")


def read_env(env_path: Path | str = DEFAULT_ENV_PATH) -> dict[str, str]:
    p = Path(env_path)
    if not p.exists():
        return {}
    return parse_env(p.read_text(encoding="utf-8"))


def write_env_updates(
    updates: dict[str, str], env_path: Path | str = DEFAULT_ENV_PATH
) -> Settings:
    """Merge-write managed keys (empty string = clear) and return fresh Settings."""
    p = Path(env_path)
    merged = merge_env(read_env(p), updates)
    merged = {k: v for k, v in merged.items() if v != ""}
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(format_env(merged), encoding="utf-8")
    os.replace(tmp, p)
    get_settings.cache_clear()
    return Settings(_env_file=p)  # type: ignore[call-arg]
