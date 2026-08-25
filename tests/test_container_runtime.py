from pathlib import Path

import pytest

from resume_agent.container_runtime import configure_environment, resolve_app_mode

ROOT = Path(__file__).resolve().parents[1]


def test_container_defaults_to_local_mode_without_hosted_settings():
    environment: dict[str, str] = {}

    mode = configure_environment(environment)

    assert mode == "local"
    assert environment["BROWSER_ENABLED"] == "false"
    assert environment["SECURE_COOKIES"] == "false"
    assert environment["DISABLE_API_DOCS"] == "false"


def test_container_auto_selects_secure_hosted_mode_from_public_origin():
    environment = {"APP_BASE_URL": "https://resume.example.com"}

    mode = configure_environment(environment)

    assert mode == "hosted"
    assert environment["SECURE_COOKIES"] == "true"
    assert environment["DISABLE_API_DOCS"] == "true"
    assert environment["REGISTRATION_MODE"] == "open"


def test_hosted_mode_preserves_safe_overrides_but_forces_secure_cookies():
    environment = {
        "APP_MODE": "hosted",
        "SECURE_COOKIES": "false",
        "DISABLE_API_DOCS": "false",
        "REGISTRATION_MODE": "invite",
    }

    assert configure_environment(environment) == "hosted"
    assert environment["SECURE_COOKIES"] == "true"
    assert environment["DISABLE_API_DOCS"] == "false"
    assert environment["REGISTRATION_MODE"] == "invite"


def test_invalid_container_mode_fails_loudly():
    with pytest.raises(ValueError, match="APP_MODE"):
        resolve_app_mode({"APP_MODE": "public"})


def test_image_uses_non_root_runtime_and_does_not_copy_local_config():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "USER resume-agent" in dockerfile
    assert 'ENTRYPOINT ["python", "-m", "resume_agent.container_runtime"]' in dockerfile
    assert "COPY config ./config.defaults" not in dockerfile
    assert "config/*" in dockerignore
    assert "!config/*.example" in dockerignore


def test_compose_binds_localhost_and_persists_the_data_root():
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert '"127.0.0.1:${RESUME_AGENT_PORT:-8000}:8000"' in compose
    assert "APP_MODE: local" in compose
    assert "resume-agent-data:/app/data" in compose
