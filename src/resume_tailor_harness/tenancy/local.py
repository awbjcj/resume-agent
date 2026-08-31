from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from resume_tailor_harness.config import env_settings
from resume_tailor_harness.tenancy.bootstrap import build_context
from resume_tailor_harness.tenancy.context import UserContext, activate
from resume_tailor_harness.tenancy.engines import EngineRegistry
from resume_tailor_harness.tenancy.system_db import User, init_system_db, make_system_engine
from resume_tailor_harness.tenancy.workspace import WorkspacePaths


def rebase_cli_path(path: Path | str, workspace: WorkspacePaths) -> Path:
    candidate = Path(path)
    normalized = candidate.as_posix()
    if normalized == "data":
        return workspace.root
    if normalized.startswith("data/"):
        return workspace.root / normalized.removeprefix("data/")
    if normalized == "config":
        return workspace.config_dir
    if normalized.startswith("config/"):
        return workspace.config_dir / normalized.removeprefix("config/")
    if normalized == "output":
        return workspace.output_dir
    if normalized.startswith("output/"):
        return workspace.output_dir / normalized.removeprefix("output/")
    return candidate


def resolve_local_context(
    data_root: Path | str = Path("data"), username: str | None = None
) -> UserContext | None:
    root = Path(data_root)
    if not (root / "system.db").is_file():
        if username is not None:
            raise RuntimeError(f"--user requires a multi-user data root at {root}")
        return None
    system_engine = make_system_engine(root)
    init_system_db(system_engine)
    with Session(system_engine) as session:
        query = select(User)
        if username is not None:
            query = query.where(User.username == username)
        else:
            query = query.where(User.role == "admin").order_by(User.created_at)
        user = session.execute(query).scalars().first()
        if user is None:
            system_engine.dispose()
            identity = f"user {username!r}" if username else "an admin"
            raise RuntimeError(f"could not find {identity} in {root}")
        session.expunge(user)
    return build_context(
        user,
        root,
        env_settings(),
        EngineRegistry(),
        system_engine=system_engine,
    )


def activate_local_context(
    data_root: Path | str = Path("data"), username: str | None = None
) -> UserContext | None:
    context = resolve_local_context(data_root, username)
    if context is not None:
        activate(context)
    return context
