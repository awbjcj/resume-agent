"""Container startup that supports both zero-config local and hosted modes."""

from __future__ import annotations

import os
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import cast

from resume_agent.config import AppMode
from resume_agent.deploy import main as prepare_data_root

APP_MODES = {"auto", "local", "hosted"}


def _drop_privileges_to_app_user() -> None:
    """Reclaim the mounted data volume, then drop from root to resume-agent.

    The image bakes ownership of /app into the resume-agent user at build
    time, but /app/data is a Railway volume: its ownership is whatever UID
    last wrote to it, not what the current image says. `useradd --system`
    allocates the next free system UID from the base image, so a routine
    rebuild of the floating `python:3.13-slim` tag can silently hand
    resume-agent a different UID than the one the volume's existing files
    are owned by, and every write inside it starts failing with
    PermissionError. Running as root just long enough to chown the volume
    to the current build's UID before dropping privileges makes this
    self-healing regardless of how the UID drifts between builds.
    """
    if os.geteuid() != 0:
        return
    import pwd

    user = pwd.getpwnam("resume-agent")
    app_root = Path(os.environ.get("APP_ROOT", "/app"))
    data_root = Path(os.environ.get("DATA_ROOT", str(app_root / "data")))
    if data_root.exists():
        for dirpath, dirnames, filenames in os.walk(data_root):
            os.chown(dirpath, user.pw_uid, user.pw_gid)
            for name in filenames:
                os.chown(os.path.join(dirpath, name), user.pw_uid, user.pw_gid)
    os.setgroups([])
    os.setgid(user.pw_gid)
    os.setuid(user.pw_uid)


def resolve_app_mode(environ: Mapping[str, str]) -> AppMode:
    """Resolve the explicit mode, or infer hosted mode from hosted-only settings."""
    requested = environ.get("APP_MODE", "auto").strip().casefold()
    if requested not in APP_MODES:
        choices = ", ".join(sorted(APP_MODES))
        raise ValueError(f"APP_MODE must be one of: {choices}")
    if requested in ("local", "hosted"):
        return cast(AppMode, requested)
    hosted_markers = ("APP_BASE_URL", "AUTH_PASSWORD_HASH", "SESSION_SECRET")
    return (
        "hosted"
        if any(environ.get(name, "").strip() for name in hosted_markers)
        else "local"
    )


def configure_environment(environ: MutableMapping[str, str]) -> AppMode:
    """Apply mode-aware defaults and enforce the hosted HTTPS boundary."""
    mode = resolve_app_mode(environ)
    environ.setdefault("BROWSER_ENABLED", "false")
    if mode == "hosted":
        # Hosted containers are an internet-facing boundary. Do not allow an
        # environment override to bypass create_app's canonical-HTTPS check.
        environ["SECURE_COOKIES"] = "true"
        environ.setdefault("DISABLE_API_DOCS", "true")
        environ.setdefault("REGISTRATION_MODE", "open")
    else:
        environ.setdefault("SECURE_COOKIES", "false")
        environ.setdefault("DISABLE_API_DOCS", "false")
    return mode


def main() -> None:
    import uvicorn

    from resume_agent.api.app import create_app

    _drop_privileges_to_app_user()
    prepare_data_root()
    mode = configure_environment(os.environ)
    try:
        port = int(os.environ.get("PORT", "8000"))
    except ValueError as exc:
        raise SystemExit("PORT must be an integer") from exc
    uvicorn.run(create_app(app_mode=mode), host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
