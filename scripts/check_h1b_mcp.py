"""Verify the local H-1B Streamable HTTP MCP connection.

This probe uses the same Agno MCP client and read-only tool allowlist as the
resume-tailor-harness integration, so a successful HTTP health response alone cannot
hide a broken MCP handshake or tool discovery step.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence

from agno.tools.mcp import MCPTools


EXPECTED_TOOLS = {
    "get_available_data",
    "get_company_stats",
    "search_h1b_jobs",
}


async def _probe(url: str, timeout: int) -> set[str]:
    tools = MCPTools(
        url=url,
        transport="streamable-http",
        include_tools=sorted(EXPECTED_TOOLS),
        tool_name_prefix="h1b",
        timeout_seconds=timeout,
    )
    await tools.connect()
    try:
        if not getattr(tools, "_initialized", False):
            raise RuntimeError("MCP handshake or tool discovery did not complete")
        return {
            name.removeprefix("h1b_")
            for name in tools.functions
            if name.startswith("h1b_")
        }
    finally:
        await tools.close()


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="MCP Streamable HTTP URL")
    parser.add_argument("--timeout", type=int, default=30, help="MCP read timeout")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        discovered = asyncio.run(_probe(args.url, args.timeout))
    except Exception as error:  # pragma: no cover - exercised by live checks
        print(f"H1B MCP connection failed: {error}", file=sys.stderr)
        return 1

    missing = EXPECTED_TOOLS - discovered
    if missing:
        print(
            "H1B MCP connection succeeded but required tools are missing: "
            + ", ".join(sorted(missing)),
            file=sys.stderr,
        )
        return 1

    print("H1B MCP connection OK: " + ", ".join(sorted(discovered)) + f" at {args.url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
