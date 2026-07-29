from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.api.deps import get_settings_dep
from resume_agent.config import env_settings


def _client(**kw):
    return TestClient(create_app(db_url="sqlite://", **kw))


def test_health_ok():
    resp = _client().get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {
        "status": "ok",
        "mailConfigured": False,
        "googleOauthConfigured": False,
    }


def test_no_auth_by_default():
    assert _client().get("/api/health").status_code == 200


def test_api_tests_ignore_host_auth_environment(monkeypatch):
    monkeypatch.setenv("API_TOKEN", "host-token-that-tests-must-not-inherit")
    env_settings.cache_clear()
    try:
        with _client() as client:
            assert client.get("/api/pipeline").status_code == 200
    finally:
        env_settings.cache_clear()


def test_bearer_required_when_token_set():
    client = _client(api_token="secret")
    with client:
        assert client.get("/api/health").status_code == 200  # health is unguarded
        assert client.get("/api/pipeline").status_code == 401
        assert client.get("/api/pipeline?token=secret").status_code == 200


def test_settings_isolated_to_custom_env_path_at_startup(tmp_path):
    """create_app(env_path=...) must build startup settings from that file, not
    the process-wide cached Settings() (which reads the real cwd .env) — else a
    test/deployment passing a custom env_path still gets the real file's
    secrets into app.state.settings until the first write-triggered refresh."""
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=sk-ant-isolated-0001\n", encoding="utf-8")
    app = create_app(db_url="sqlite://", env_path=env)
    with TestClient(app):
        assert app.dependency_overrides[get_settings_dep]().anthropic_api_key == (
            "sk-ant-isolated-0001"
        )
