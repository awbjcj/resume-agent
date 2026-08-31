from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from resume_tailor_harness.config import Settings
from resume_tailor_harness.tenancy.context import UserContext, new_user_id
from resume_tailor_harness.tenancy.engines import EngineRegistry
from resume_tailor_harness.tenancy.migrate import adopt_legacy_root, is_legacy_root
from resume_tailor_harness.tenancy.system_db import User, utc_now
from resume_tailor_harness.tenancy.workspace import (
    effective_settings,
    provision_workspace,
    workspace_paths,
)


class BootstrapError(RuntimeError):
    pass


def ensure_local_user(
    data_root: Path | str, system_engine: Engine, settings: Settings
) -> User:
    """Return the one implicit local user without requiring login credentials.

    Local mode keeps using the canonical workspace layout so a checkout can be
    opened by the hosted server later, but it never performs tenant selection.
    An existing administrator is the stable default. A fresh checkout receives
    a local administrator whose empty password cannot be used for hosted login.
    """

    root = Path(data_root)
    with Session(system_engine) as session:
        admin = (
            session.execute(
                select(User).where(User.role == "admin").order_by(User.created_at)
            )
            .scalars()
            .first()
        )
        if admin is None:
            user_count = int(
                session.execute(select(func.count()).select_from(User)).scalar_one()
            )
            if user_count:
                raise BootstrapError("users table is non-empty but has no admin")
            admin = User(
                id=new_user_id(),
                username=settings.auth_username.strip() or "local",
                password_hash=settings.auth_password_hash,
                email=settings.auth_email or None,
                email_verified_at=utc_now() if settings.auth_email else None,
                role="admin",
            )
            session.add(admin)
            session.commit()
            session.refresh(admin)
        session.expunge(admin)

    # A completed workspace wins over stale legacy children left at data/. This
    # is what makes local restart tolerant of partially migrated old checkouts.
    if is_legacy_root(root) and not workspace_paths(root, admin.id).db_file.is_file():
        adopt_legacy_root(root, admin.id)
    provision_workspace(root, admin.id)
    return admin


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
                email=settings.auth_email or None,
                email_verified_at=utc_now() if settings.auth_email else None,
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
    platform_provider_keys = {
        provider: key
        for provider, key in {
            "anthropic": base_settings.anthropic_api_key,
            "openai": base_settings.openai_api_key,
            "gemini": base_settings.gemini_api_key,
            "deepseek": base_settings.deepseek_api_key,
        }.items()
        if key
    }
    return UserContext(
        user_id=user.id,
        username=user.username,
        role=user.role,
        paths=paths,
        settings=overlay.settings,
        engine=registry.get(user.id, paths.db_url),
        system_engine=system_engine,
        own_key_providers=overlay.own_key_providers,
        platform_provider_keys=platform_provider_keys,
        user_provider_keys=overlay.user_provider_keys,
    )
