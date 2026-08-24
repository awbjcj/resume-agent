"""FastAPI application factory — the third adapter over the domain code."""

from __future__ import annotations

import asyncio
from concurrent.futures import Executor
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from resume_agent.api.deps import (
    get_download_user_context,
    get_settings_dep,
    get_user_context,
    require_token,
)
from resume_agent.api.errors import ApiException, install_error_handlers
from resume_agent.api.password_policy import HibpBreachChecker
from resume_agent.api.routers import account as account_router
from resume_agent.api.routers import admin as admin_router
from resume_agent.api.routers import admin_invites as admin_invites_router
from resume_agent.api.routers import admin_quotas as admin_quotas_router
from resume_agent.api.routers import admin_system as admin_system_router
from resume_agent.api.routers import admin_routing as admin_routing_router
from resume_agent.api.routers import admin_users as admin_users_router
from resume_agent.api.routers import analytics as analytics_router
from resume_agent.api.routers import auth as auth_router
from resume_agent.api.routers import auth_google as auth_google_router
from resume_agent.api.routers import auth_password as auth_password_router
from resume_agent.api.routers import auth_register as auth_register_router
from resume_agent.api.routers import boards, health, resumes
from resume_agent.api.routers import coach as coach_router
from resume_agent.api.routers import career_lab as career_lab_router
from resume_agent.api.routers import config as config_router
from resume_agent.api.routers import cover_letters as cover_letters_router
from resume_agent.api.routers import dashboard as dashboard_router
from resume_agent.api.routers import email_drafts as email_drafts_router
from resume_agent.api.routers import errors as errors_router
from resume_agent.api.routers import gmail as gmail_router
from resume_agent.api.routers import interview as interview_router
from resume_agent.api.routers import jobs as jobs_router
from resume_agent.api.routers import match_gap as match_gap_router
from resume_agent.api.routers import notifications as notifications_router
from resume_agent.api.routers import profile as profile_router
from resume_agent.api.routers import prompts as prompts_router
from resume_agent.api.routers import prune as prune_router
from resume_agent.api.routers import render_templates as render_templates_router
from resume_agent.api.routers import runs as runs_router
from resume_agent.api.routers import scout as scout_router
from resume_agent.api.routers import secrets as secrets_router
from resume_agent.api.routers import settings as settings_router
from resume_agent.api.routers import setup as setup_router
from resume_agent.api.routers import sources as sources_router
from resume_agent.api.routers import suggestions as suggestions_router
from resume_agent.api.routers import taxonomy as taxonomy_router
from resume_agent.api.routers import transcribe as transcribe_router
from resume_agent.api.runs.manager import RunManager
from resume_agent.api.public_url import validate_public_origin
from resume_agent.config import AppMode, Settings, get_settings
from resume_agent.db import init_db, make_engine
from resume_agent.services.config_store import YamlConfigStore
from resume_agent.services.profile_documents import DocumentStore
from resume_agent.tenancy.bootstrap import (
    build_context,
    ensure_bootstrapped,
    ensure_local_user,
)
from resume_agent.tenancy.context import current_context
from resume_agent.tenancy.engines import EngineRegistry
from resume_agent.tenancy.system_db import init_system_db, make_system_engine
from resume_agent.mail.mailer import build_mailer
from resume_agent.tenancy.workspace import workspace_paths


def spa_dist_dir() -> Path:
    """Location of the built React SPA (repo_root/web/dist).

    app.py lives at src/resume_agent/api/app.py, so the repo root is parents[3].
    """
    return Path(__file__).resolve().parents[3] / "web" / "dist"


def _is_memory_db(db_url: str) -> bool:
    return db_url in {"sqlite://", "sqlite://:memory:", "sqlite:///:memory:"}


def create_app(
    *,
    db_url: str | None = None,
    app_mode: AppMode = "local",
    api_token: str | None = None,
    run_executor: Executor | None = None,
    runs_root: Path | str | None = None,
    config_dir: Path | str | None = None,
    env_path: Path | str | None = None,
    data_dir: Path | str | None = None,
) -> FastAPI:
    # A caller-supplied env_path is a distinct settings source (test isolation,
    # or a non-default deployment layout) — read it directly rather than the
    # process-wide get_settings() cache, which is pinned to cwd-relative ".env"
    # and would otherwise leak that file's values into this app instance.
    settings = (
        Settings(_env_file=Path(env_path))  # type: ignore[call-arg]
        if env_path is not None
        else get_settings()
    )
    resolved_db = db_url or settings.db_url
    resolved_token = settings.api_token if api_token is None else api_token
    resolved_settings = settings.model_copy(
        update={"db_url": resolved_db, "api_token": resolved_token}
    )
    if resolved_settings.secure_cookies:
        if not resolved_settings.app_base_url:
            raise RuntimeError("APP_BASE_URL is required when SECURE_COOKIES=true")
        if not validate_public_origin(resolved_settings.app_base_url).startswith(
            "https://"
        ):
            raise RuntimeError("APP_BASE_URL must use HTTPS when SECURE_COOKIES=true")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if _is_memory_db(resolved_db):
            engine = make_engine(resolved_db)
            init_db(engine)
            app.state.system_engine = None
            app.state.engine_registry = None
            app.state.default_context = None
            app.state.engine = engine
        else:
            system_engine = make_system_engine(app.state.data_dir)
            try:
                init_system_db(system_engine)
                default_user = (
                    ensure_bootstrapped(
                        app.state.data_dir, system_engine, app.state.settings
                    )
                    if app.state.app_mode == "hosted"
                    else ensure_local_user(
                        app.state.data_dir, system_engine, app.state.settings
                    )
                )
                registry = EngineRegistry()
                context = build_context(
                    default_user,
                    app.state.data_dir,
                    app.state.settings,
                    registry,
                    system_engine=system_engine,
                    template_dir=app.state.template_config_dir,
                )
            except BaseException:
                system_engine.dispose()
                raise
            app.state.system_engine = system_engine
            app.state.engine_registry = registry
            app.state.default_context = context
            app.state.engine = context.engine
            for root in (app.state.data_dir / "users").glob("*/runs"):
                app.state.run_manager.register_root(root)
        app.state.run_manager.recover_interrupted()
        app.state.run_manager.sweep()  # drop stale run records (unbounded otherwise)
        app.state.gmail_scheduler_task = None
        if (
            not _is_memory_db(resolved_db)
            and resolved_settings.gmail_sync_interval_hours > 0
        ):
            from resume_agent.gmail.scheduler import scheduler_loop

            app.state.gmail_scheduler_task = asyncio.create_task(
                scheduler_loop(app.state)
            )
        yield
        if app.state.gmail_scheduler_task is not None:
            app.state.gmail_scheduler_task.cancel()
            with suppress(asyncio.CancelledError):
                await app.state.gmail_scheduler_task
        app.state.run_manager.shutdown()
        if app.state.engine_registry is not None:
            app.state.engine_registry.close_all()
        elif app.state.engine is not None:
            app.state.engine.dispose()
        if app.state.system_engine is not None:
            app.state.system_engine.dispose()

    docs_url = None if resolved_settings.disable_api_docs else "/docs"
    redoc_url = None if resolved_settings.disable_api_docs else "/redoc"
    openapi_url = None if resolved_settings.disable_api_docs else "/openapi.json"
    app = FastAPI(
        title="Resume Agent API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )
    app.state.app_mode = app_mode
    app.state.settings = resolved_settings
    if resolved_settings.disable_api_docs:

        def _docs_disabled() -> None:
            raise HTTPException(status_code=404)

        for disabled_path in ("/docs", "/redoc", "/openapi.json"):
            app.add_api_route(
                disabled_path,
                _docs_disabled,
                include_in_schema=False,
            )
    app.state.db_url = resolved_db
    app.state.template_config_dir = Path(config_dir or "config")
    app.state.config_store = YamlConfigStore(config_dir=app.state.template_config_dir)
    app.state.env_path = Path(env_path) if env_path is not None else Path(".env")
    app.state.data_dir = Path(data_dir or "data")
    app.state.document_store = DocumentStore(
        app.state.data_dir / "profile" / "documents"
    )
    app.state.mailer = build_mailer(resolved_settings)
    app.state.breach_checker = HibpBreachChecker()
    app.state.gmail_oauth_states = {}
    # Falls back to a path under data_dir (not the separate RUNS_ROOT constant) so
    # that overriding data_dir — as most tests do to avoid touching the real repo —
    # also isolates the run manager; otherwise runs launched with no active
    # per-request UserContext (e.g. in-memory-db tests) write into the real
    # project's data/runs regardless of data_dir.
    manager_root = runs_root if runs_root is not None else (app.state.data_dir / "runs")
    # The in-memory test adapter uses one StaticPool connection shared by every
    # thread, so concurrent sessions cannot safely transact on it. File-backed
    # SQLite and production databases retain the configured suggestion width.
    suggestion_workers = (
        1
        if resolved_db in {"sqlite://", "sqlite://:memory:", "sqlite:///:memory:"}
        else resolved_settings.suggestion_batch_concurrency
    )

    def _record_run_error(payload: dict) -> None:
        from sqlalchemy.orm import Session as SystemSession
        from sqlmodel import Session as DbSession

        from resume_agent.services.errors import record_error
        from resume_agent.tenancy.system_db import User

        context = current_context()
        engine = context.engine if context is not None else None
        user_id = payload.get("userId")
        if engine is None and user_id:
            system_engine = getattr(app.state, "system_engine", None)
            registry = getattr(app.state, "engine_registry", None)
            if system_engine is None or registry is None:
                return
            with SystemSession(system_engine) as system_session:
                if system_session.get(User, str(user_id)) is None:
                    return
            paths = workspace_paths(app.state.data_dir, str(user_id))
            engine = registry.get(str(user_id), paths.db_url)
        if engine is None:
            engine = getattr(app.state, "engine", None)
        if engine is None:
            return
        with DbSession(engine) as database:
            record_error(
                database,
                kind="run",
                source_label=str(payload.get("kind") or "run"),
                message=str(payload.get("error") or "unknown error"),
                run_id=str(payload.get("runId") or "") or None,
            )

    app.state.run_manager = RunManager(
        root=manager_root,
        executor=run_executor,
        kind_workers=(
            {"suggestion": suggestion_workers} if run_executor is None else None
        ),
        on_error=_record_run_error,
    )

    def _settings_override() -> Settings:
        ctx = current_context()
        return ctx.settings if ctx is not None else app.state.settings

    app.dependency_overrides[get_settings_dep] = _settings_override
    allowed_hosts = [
        host.strip()
        for host in resolved_settings.allowed_hosts.split(",")
        if host.strip()
    ]
    if resolved_settings.app_base_url:
        from urllib.parse import urlsplit

        configured_host = urlsplit(resolved_settings.app_base_url).hostname
        if configured_host and configured_host not in allowed_hosts:
            allowed_hosts.append(configured_host)
    if allowed_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
    origins = [
        o.strip() for o in resolved_settings.cors_origins.split(",") if o.strip()
    ]
    # Production and Vite's /api proxy are same-origin. Cross-origin cookie auth
    # remains intentionally disabled so wildcard CORS cannot leak credentials.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    install_error_handlers(app)

    # Guard application routes through the selected runtime mode. Local mode
    # activates the default workspace; hosted mode authenticates a tenant.
    guarded = [Depends(require_token), Depends(get_user_context)]
    app.include_router(health.router, prefix="/api")
    app.include_router(auth_router.router, prefix="/api")
    app.include_router(auth_google_router.router, prefix="/api")
    app.include_router(auth_google_router.callback_router, prefix="/api")
    app.include_router(auth_register_router.router, prefix="/api")
    app.include_router(auth_password_router.router, prefix="/api")
    app.include_router(auth_router.link_router, prefix="/api", dependencies=guarded)
    download_guarded = [Depends(require_token), Depends(get_download_user_context)]
    app.include_router(
        account_router.link_router, prefix="/api", dependencies=download_guarded
    )
    app.include_router(
        admin_router.link_router, prefix="/api", dependencies=download_guarded
    )
    app.include_router(
        resumes.link_router, prefix="/api", dependencies=download_guarded
    )
    app.include_router(
        cover_letters_router.link_router,
        prefix="/api",
        dependencies=download_guarded,
    )
    app.include_router(
        settings_router.link_router, prefix="/api", dependencies=download_guarded
    )
    app.include_router(account_router.router, prefix="/api", dependencies=guarded)
    app.include_router(boards.router, prefix="/api", dependencies=guarded)
    app.include_router(jobs_router.router, prefix="/api", dependencies=guarded)
    app.include_router(resumes.router, prefix="/api", dependencies=guarded)
    app.include_router(cover_letters_router.router, prefix="/api", dependencies=guarded)
    app.include_router(prune_router.router, prefix="/api", dependencies=guarded)
    app.include_router(
        runs_router.link_router,
        prefix="/api",
        dependencies=[Depends(require_token)],
    )
    app.include_router(runs_router.router, prefix="/api", dependencies=guarded)
    app.include_router(sources_router.router, prefix="/api", dependencies=guarded)
    app.include_router(scout_router.router, prefix="/api", dependencies=guarded)
    app.include_router(analytics_router.router, prefix="/api", dependencies=guarded)
    app.include_router(match_gap_router.router, prefix="/api", dependencies=guarded)
    app.include_router(taxonomy_router.router, prefix="/api", dependencies=guarded)
    app.include_router(suggestions_router.router, prefix="/api", dependencies=guarded)
    app.include_router(notifications_router.router, prefix="/api", dependencies=guarded)
    app.include_router(gmail_router.router, prefix="/api", dependencies=guarded)
    app.include_router(gmail_router.callback_router, prefix="/api")
    app.include_router(email_drafts_router.router, prefix="/api", dependencies=guarded)
    app.include_router(config_router.router, prefix="/api", dependencies=guarded)
    app.include_router(settings_router.router, prefix="/api", dependencies=guarded)
    app.include_router(
        render_templates_router.router, prefix="/api", dependencies=guarded
    )
    app.include_router(prompts_router.router, prefix="/api", dependencies=guarded)
    app.include_router(secrets_router.router, prefix="/api", dependencies=guarded)
    app.include_router(profile_router.router, prefix="/api", dependencies=guarded)
    app.include_router(coach_router.router, prefix="/api", dependencies=guarded)
    app.include_router(career_lab_router.router, prefix="/api", dependencies=guarded)
    app.include_router(interview_router.router, prefix="/api", dependencies=guarded)
    app.include_router(transcribe_router.router, prefix="/api", dependencies=guarded)
    app.include_router(setup_router.router, prefix="/api", dependencies=guarded)
    app.include_router(dashboard_router.router, prefix="/api", dependencies=guarded)
    app.include_router(errors_router.router, prefix="/api", dependencies=guarded)
    app.include_router(admin_router.router, prefix="/api", dependencies=guarded)
    app.include_router(admin_users_router.router, prefix="/api", dependencies=guarded)
    app.include_router(admin_invites_router.router, prefix="/api", dependencies=guarded)
    app.include_router(admin_system_router.router, prefix="/api", dependencies=guarded)
    app.include_router(admin_routing_router.router, prefix="/api", dependencies=guarded)
    app.include_router(admin_quotas_router.router, prefix="/api", dependencies=guarded)

    # Serve the built SPA when present. Registered AFTER the API + docs routes so
    # they take precedence; the catch-all is excluded from the OpenAPI schema so
    # it never appears in the generated contract.
    dist = spa_dist_dir()
    if dist.is_dir():
        assets = dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            # Unknown API paths must 404 with the JSON envelope, not the SPA shell,
            # so API clients don't mis-parse an HTML 200.
            if full_path == "api" or full_path.startswith("api/"):
                raise ApiException(404, "NOT_FOUND", f"No route for /{full_path}")
            dist_root = dist.resolve()
            candidate = (dist_root / full_path).resolve()
            if full_path:
                if not candidate.is_relative_to(dist_root):
                    raise ApiException(404, "NOT_FOUND", f"No route for /{full_path}")
                if candidate.is_file():
                    return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app
