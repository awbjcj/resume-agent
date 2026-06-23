"""FastAPI application factory — the third adapter over the domain code."""

from __future__ import annotations

from concurrent.futures import Executor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from resume_agent.api.deps import get_settings_dep, require_token
from resume_agent.api.errors import ApiException, install_error_handlers
from resume_agent.api.routers import analytics as analytics_router
from resume_agent.api.routers import boards, health
from resume_agent.api.routers import jobs as jobs_router
from resume_agent.api.routers import match_gap as match_gap_router
from resume_agent.api.routers import prune as prune_router
from resume_agent.api.routers import resumes
from resume_agent.api.routers import runs as runs_router
from resume_agent.api.runs.manager import RunManager
from resume_agent.config import get_settings
from resume_agent.db import init_db, make_engine


def spa_dist_dir() -> Path:
    """Location of the built React SPA (repo_root/web/dist).

    app.py lives at src/resume_agent/api/app.py, so the repo root is parents[3].
    """
    return Path(__file__).resolve().parents[3] / "web" / "dist"


def create_app(
    *,
    db_url: str | None = None,
    api_token: str | None = None,
    run_executor: Executor | None = None,
    runs_root: Path | str | None = None,
) -> FastAPI:
    settings = get_settings()
    resolved_db = db_url or settings.db_url
    resolved_token = settings.api_token if api_token is None else api_token
    resolved_settings = settings.model_copy(
        update={"db_url": resolved_db, "api_token": resolved_token}
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = make_engine(resolved_db)
        init_db(engine)
        app.state.engine = engine
        app.state.run_manager.sweep()  # drop stale run records (unbounded otherwise)
        yield
        app.state.run_manager.shutdown()

    app = FastAPI(title="Resume Agent API", version="0.1.0", lifespan=lifespan)
    app.state.settings = resolved_settings
    app.state.db_url = resolved_db
    app.state.run_manager = (
        RunManager(root=runs_root, executor=run_executor)
        if runs_root is not None
        else RunManager(executor=run_executor)
    )
    app.dependency_overrides[get_settings_dep] = lambda: resolved_settings

    origins = [o.strip() for o in resolved_settings.cors_origins.split(",") if o.strip()]
    # Auth is a static bearer token in the Authorization header (not cookies), so
    # allow_credentials stays False — that keeps a wildcard/`*` origin valid instead
    # of silently breaking credentialed requests (the classic CORS footgun).
    app.add_middleware(
        CORSMiddleware, allow_origins=origins, allow_credentials=False,
        allow_methods=["*"], allow_headers=["*"],
    )

    install_error_handlers(app)

    # Guard everything except /api/health behind the optional bearer token.
    guarded = [Depends(require_token)]
    app.include_router(health.router, prefix="/api")
    app.include_router(boards.router, prefix="/api", dependencies=guarded)
    app.include_router(jobs_router.router, prefix="/api", dependencies=guarded)
    app.include_router(resumes.router, prefix="/api", dependencies=guarded)
    app.include_router(prune_router.router, prefix="/api", dependencies=guarded)
    app.include_router(runs_router.router, prefix="/api", dependencies=guarded)
    app.include_router(analytics_router.router, prefix="/api", dependencies=guarded)
    app.include_router(match_gap_router.router, prefix="/api", dependencies=guarded)

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
