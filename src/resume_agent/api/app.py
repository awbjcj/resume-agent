"""FastAPI application factory — the third adapter over the domain code."""

from __future__ import annotations

from concurrent.futures import Executor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from resume_agent.api.deps import get_settings_dep, require_token
from resume_agent.api.errors import install_error_handlers
from resume_agent.api.routers import health
from resume_agent.config import get_settings
from resume_agent.db import init_db, make_engine


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
        yield

    app = FastAPI(title="Resume Agent API", version="0.1.0", lifespan=lifespan)
    app.state.settings = resolved_settings
    app.state.db_url = resolved_db
    app.dependency_overrides[get_settings_dep] = lambda: resolved_settings

    origins = [o.strip() for o in resolved_settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware, allow_origins=origins, allow_credentials=True,
        allow_methods=["*"], allow_headers=["*"],
    )

    install_error_handlers(app)

    # Guard everything except /api/health behind the optional bearer token.
    guarded = [Depends(require_token)]  # noqa: F841  (used by routers added in later tasks)
    app.include_router(health.router, prefix="/api")
    # (subsequent routers are included with dependencies=guarded in later tasks)

    return app
