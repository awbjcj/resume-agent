"""Regression test for the nested-async-generator context leak.

``get_user_context`` (and its SSE/download siblings) wrap ``_activate_user_context``
via ``async for context in _activate_user_context(request): yield context``. That
pattern does not close the inner generator when the outer one is closed, so the
``UserContext`` contextvar token set by ``use_context`` was never reset in the same
task -- it only got reset later, from an unrelated Context, by CPython's async
generator GC finalizer, which raised ``ValueError: ... created in a different
Context``. This test closes the dependency generator directly (as FastAPI's own
dependency-injection ``AsyncExitStack`` does at the end of a request) and asserts
the contextvar is reset immediately, in the same task -- no GC timing involved.
"""

from __future__ import annotations

import types
from typing import cast

from fastapi import Request

from resume_agent.api import deps
from resume_agent.tenancy.context import current_context


class _DummyRunManager:
    def register_root(self, root) -> None:
        pass


class _DummyUser:
    disabled_at = None


def _dummy_context() -> types.SimpleNamespace:
    return types.SimpleNamespace(paths=types.SimpleNamespace(runs_root="/tmp/runs"))


def _fake_request() -> types.SimpleNamespace:
    app = types.SimpleNamespace(
        state=types.SimpleNamespace(
            system_engine=object(),
            run_manager=_DummyRunManager(),
            data_dir="/tmp/data",
            settings=None,
            engine_registry=None,
            template_config_dir=None,
        )
    )
    return types.SimpleNamespace(app=app)


async def test_get_user_context_resets_contextvar_when_closed(monkeypatch):
    monkeypatch.setattr(
        deps, "_authenticated_user", lambda request, *, link_purpose=None: _DummyUser()
    )
    monkeypatch.setattr(deps, "build_context", lambda *args, **kwargs: _dummy_context())

    # The stub only needs the ``app.state`` attributes the dependency reads.
    request = cast(Request, _fake_request())
    agen = deps.get_user_context(request)
    context = await agen.__anext__()
    assert current_context() is context

    await agen.aclose()

    assert current_context() is None
