import asyncio

import pytest

from resume_agent.config import Settings
from resume_agent.h1b.mcp import (
    H1B_INCLUDE_TOOLS,
    H1BResultTooLarge,
    bounded_h1b_result,
    h1b_tools,
)


class FakeMCP:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.connected = 0
        self.closed = 0
        self.include_tools = kwargs["include_tools"]
        self.tool_name_prefix = kwargs["tool_name_prefix"]
        type(self).instances.append(self)

    async def connect(self):
        self.connected += 1

    async def close(self):
        self.closed += 1


def _settings():
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        h1b_mcp_enabled=True,
        h1b_mcp_transport="stdio",
        h1b_mcp_command="h1b-server",
    )


def test_toolkit_exposes_only_prefixed_read_tools():
    FakeMCP.instances.clear()

    async def run():
        async with h1b_tools(_settings(), mcp_type=FakeMCP) as tools:
            assert tools.include_tools == H1B_INCLUDE_TOOLS
            assert tools.tool_name_prefix == "h1b"
            assert tools.kwargs["transport"] == "stdio"

    asyncio.run(run())
    assert FakeMCP.instances[0].connected == 1
    assert FakeMCP.instances[0].closed == 1


def test_partial_startup_still_closes_toolkit():
    class FailingMCP(FakeMCP):
        async def connect(self):
            self.connected += 1
            raise RuntimeError("startup")

    async def run():
        with pytest.raises(RuntimeError, match="startup"):
            async with h1b_tools(_settings(), mcp_type=FailingMCP):
                pass

    asyncio.run(run())
    assert FailingMCP.instances[-1].closed == 1


def test_result_hook_rejects_oversized_provider_payload():
    hook = bounded_h1b_result(4)

    async def run():
        with pytest.raises(H1BResultTooLarge):
            await hook(lambda **_: "12345", {})

    asyncio.run(run())
