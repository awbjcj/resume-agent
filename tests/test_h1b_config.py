import pytest
from pydantic import ValidationError

from resume_tailor_harness.config import Settings


@pytest.mark.parametrize(
    "env",
    [
        {"H1B_MCP_ENABLED": "true", "H1B_MCP_TRANSPORT": "stdio"},
        {"H1B_MCP_ENABLED": "true", "H1B_MCP_TRANSPORT": "streamable-http"},
        {
            "H1B_MCP_ENABLED": "true",
            "H1B_MCP_TRANSPORT": "stdio",
            "H1B_MCP_COMMAND": "server",
            "H1B_MCP_URL": "https://example.com/mcp",
        },
    ],
)
def test_enabled_h1b_requires_exactly_one_transport_target(monkeypatch, env):
    for name in (
        "H1B_MCP_ENABLED",
        "H1B_MCP_TRANSPORT",
        "H1B_MCP_COMMAND",
        "H1B_MCP_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_disabled_h1b_ignores_transport_targets():
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        h1b_mcp_enabled=False,
        h1b_mcp_transport="streamable-http",
        h1b_mcp_command="ignored",
        h1b_mcp_url="not a url",
    )
    assert settings.h1b_mcp_enabled is False


@pytest.mark.parametrize(
    "url", ["ftp://example.com", "https://user:pass@example.com/mcp", "/relative"]
)
def test_enabled_http_h1b_rejects_unsafe_urls(url):
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,  # type: ignore[call-arg]
            h1b_mcp_enabled=True,
            h1b_mcp_transport="streamable-http",
            h1b_mcp_url=url,
        )
