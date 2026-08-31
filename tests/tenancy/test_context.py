from pathlib import Path

import pytest

from resume_tailor_harness.config import Settings
from resume_tailor_harness.tenancy.context import (
    UserContext,
    current_context,
    new_user_id,
    require_context,
    use_context,
)
from resume_tailor_harness.tenancy.workspace import WorkspacePaths


def make_ctx(**overrides) -> UserContext:
    defaults = {
        "user_id": "abc123def456",
        "username": "alice",
        "role": "user",
        "paths": WorkspacePaths(Path("data/users/abc123def456")),
        "settings": Settings(
            _env_file=None,  # type: ignore[call-arg]
            anthropic_api_key="",
            openai_api_key="",
            gemini_api_key="",
            deepseek_api_key="",
        ),
        "engine": None,
        "system_engine": None,
        "own_key_providers": frozenset(),
    }
    defaults.update(overrides)
    return UserContext(**defaults)


def test_context_sets_resets_and_exposes_workspace():
    ctx = make_ctx()
    with use_context(ctx):
        assert current_context() is ctx
        assert require_context() is ctx
        assert ctx.workspace == Path("data/users/abc123def456")
    assert current_context() is None


def test_context_resets_after_exception():
    with pytest.raises(ValueError):
        with use_context(make_ctx()):
            raise ValueError("boom")
    assert current_context() is None


def test_require_context_fails_closed():
    with pytest.raises(RuntimeError, match="UserContext"):
        require_context()


def test_new_user_id_is_random_short_hex():
    first = new_user_id()
    second = new_user_id()
    assert len(first) == 12
    assert first != second
    int(first, 16)
