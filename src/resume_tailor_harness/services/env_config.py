"""Read/merge-write .env through the TUI wizard's pure helpers.

The one write path for web-managed env values. After a write, the cached
Settings singleton is cleared so run workers (which call get_settings() at
call time) see fresh values; the router additionally refreshes
app.state.settings for request-scoped dependencies.
"""

from __future__ import annotations

import os
from pathlib import Path

from resume_tailor_harness.config import Settings, env_settings
from resume_tailor_harness.setup.env_writer import format_env, merge_env, parse_env

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
    # Railway exposes the volume-backed env file through ``/app/.env`` as a
    # symlink. Replacing a temporary file over that path replaces the symlink
    # itself, leaving the next container restart unable to recreate it and the
    # update outside the persistent volume. Perform the atomic replacement at
    # the resolved target while continuing to read settings through the public
    # path callers supplied.
    write_path = p.resolve() if p.is_symlink() else p
    merged = merge_env(read_env(p), updates)
    # "empty string = clear" is a per-key contract for the keys in `updates`,
    # not a blanket sweep — a pre-existing unrelated empty-valued key must survive.
    merged = {k: v for k, v in merged.items() if not (k in updates and v == "")}
    write_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = write_path.with_suffix(write_path.suffix + ".tmp")
    tmp.write_text(format_env(merged), encoding="utf-8")
    os.replace(tmp, write_path)
    env_settings.cache_clear()
    return Settings(_env_file=p)  # type: ignore[call-arg]
