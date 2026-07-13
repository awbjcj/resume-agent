from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from resume_agent.config import Settings
from resume_agent.tenancy.context import UserContext, new_user_id
from resume_agent.tenancy.engines import EngineRegistry
from resume_agent.tenancy.migrate import adopt_legacy_root, is_legacy_root
from resume_agent.tenancy.system_db import User
from resume_agent.tenancy.workspace import effective_settings, provision_workspace


class BootstrapError(RuntimeError):
    pass


def ensure_bootstrapped(
    data_root: Path | str, system_engine: Engine, settings: Settings
) -> User:
    root = Path(data_root)
    with Session(system_engine) as session:
        user_count = int(
            session.execute(select(func.count()).select_from(User)).scalar_one()
        )
        admin = (
            session.execute(
                select(User).where(User.role == "admin").order_by(User.created_at)
            )
            .scalars()
            .first()
        )
        if user_count == 0:
            if (
                not settings.auth_username
                or not settings.auth_password_hash
                or not settings.session_secret
            ):
                raise BootstrapError(
                    "users table is empty; AUTH_USERNAME, AUTH_PASSWORD_HASH, "
                    "and SESSION_SECRET are required"
                )
            admin = User(
                id=new_user_id(),
                username=settings.auth_username,
                password_hash=settings.auth_password_hash,
                role="admin",
            )
            session.add(admin)
            session.commit()
            session.refresh(admin)
        elif admin is None:
            raise BootstrapError("users table is non-empty but has no admin")
        assert admin is not None
        session.expunge(admin)
    if is_legacy_root(root):
        adopt_legacy_root(root, admin.id)
    provision_workspace(root, admin.id)
    return admin


def build_context(
    user: User,
    data_root: Path | str,
    base_settings: Settings,
    registry: EngineRegistry,
    system_engine: Engine | None = None,
    *,
    template_dir: Path | str = Path("config"),
) -> UserContext:
    paths = provision_workspace(data_root, user.id, template_dir=template_dir)
    overlay = effective_settings(base_settings, paths)
    return UserContext(
        user_id=user.id,
        username=user.username,
        role=user.role,
        paths=paths,
        settings=overlay.settings,
        engine=registry.get(user.id, paths.db_url),
        system_engine=system_engine,
        own_key_providers=overlay.own_key_providers,
    )
