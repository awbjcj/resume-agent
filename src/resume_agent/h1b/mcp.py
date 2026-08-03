"""Owned lifecycle and allowlist for the historical H-1B MCP server."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable

H1B_INCLUDE_TOOLS = [
    "get_company_stats",
    "search_h1b_jobs",
    "get_available_data",
]


class H1BResultTooLarge(ValueError):
    code = "H1B_RESULT_TOO_LARGE"


def _serialized_size(value: object) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return len(str(value))


def bounded_h1b_result(max_chars: int) -> Callable[..., Any]:
    """Create an async Agno tool hook that bounds provider output."""
    async def hook(func: Callable[..., Any], args: dict[str, Any]) -> Any:
        result = func(**args)
        if hasattr(result, "__await__"):
            result = await result
        if _serialized_size(result) > max_chars:
            raise H1BResultTooLarge(
                f"H1B MCP result exceeds the {max_chars}-character limit"
            )
        return result

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
async def h1b_tools(settings: Any, *, mcp_type: Any | None = None) -> AsyncIterator[Any]:
    """Connect and close the owned toolkit on the same event loop."""
    if not settings.h1b_mcp_enabled:
        yield None
        return
    tools = build_h1b_tools(settings, mcp_type=mcp_type)
    try:
        await tools.connect()
        yield tools
    finally:
        await tools.close()
