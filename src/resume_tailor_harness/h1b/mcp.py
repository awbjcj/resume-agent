"""Owned lifecycle and allowlist for the historical H-1B MCP server."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable

H1B_INCLUDE_TOOLS = [
    "get_company_stats",
    "get_company_sponsorship_trend",
    "search_h1b_jobs",
    "get_available_data",
]


class H1BResultTooLarge(ValueError):
    """Why a tool observation was clipped.

    Kept as an exception type for callers that assert on it, but it is no
    longer raised through the agent loop: it names the *recorded reason* on a
    truncated observation rather than acting as control flow. See
    :func:`bounded_h1b_result`.
    """

    code = "H1B_RESULT_TOO_LARGE"


def _serialize(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


def _serialized_size(value: object) -> int:
    return len(_serialize(value))


def bounded_h1b_result(max_chars: int) -> Callable[..., Any]:
    """Create an async Agno tool hook that bounds provider output.

    An oversized payload is **clipped and returned**, never raised. The agent
    loop's contract is that every tool call receives an observation the model
    can act on — including a denial — so raising here aborted the run instead of
    letting the model narrow its query and try again. The marker is explicit so
    the model can tell a clipped answer from a complete one.
    """

    async def hook(func: Callable[..., Any], args: dict[str, Any]) -> Any:
        result = func(**args)
        if hasattr(result, "__await__"):
            result = await result
        size = _serialized_size(result)
        if size <= max_chars:
            return result
        reason = (
            f"H1B MCP result is {size} characters, over the "
            f"{max_chars}-character limit; showing a prefix only"
        )
        return {
            "truncated": True,
            "reason": reason,
            "code": H1BResultTooLarge.code,
            "data": _serialize(result)[:max_chars],
        }

    return hook


def build_h1b_tools(settings: Any, *, mcp_type: Any | None = None) -> Any:
    """Build exactly one prefixed read-only MCP toolkit."""
    if not settings.h1b_mcp_enabled:
        return None
    toolkit_type = mcp_type
    if toolkit_type is None:
        from agno.tools.mcp import MCPTools

        toolkit_type = MCPTools
    common = {
        "include_tools": list(H1B_INCLUDE_TOOLS),
        "tool_name_prefix": "h1b",
        "timeout_seconds": settings.h1b_mcp_timeout_seconds,
    }
    if settings.h1b_mcp_transport == "stdio":
        kwargs = {"command": settings.h1b_mcp_command, "transport": "stdio", **common}
    else:
        kwargs = {"url": settings.h1b_mcp_url, "transport": "streamable-http", **common}
    return toolkit_type(**kwargs)


@asynccontextmanager
async def h1b_tools(
    settings: Any, *, mcp_type: Any | None = None
) -> AsyncIterator[Any]:
    """Connect and close the owned toolkit on the same event loop.

    ``connect()`` deliberately runs *outside* the ``try``. Closing a toolkit that
    never connected raises its own error from the ``finally``, and that
    secondary error replaces the connect failure — so the caller saw "close of
    an unopened stream" instead of the transport error that actually happened.
    A connect that fails owns its own cleanup; only a connected toolkit is ours
    to close.
    """
    if not settings.h1b_mcp_enabled:
        yield None
        return
    tools = build_h1b_tools(settings, mcp_type=mcp_type)
    await tools.connect()
    try:
        yield tools
    finally:
        await tools.close()
