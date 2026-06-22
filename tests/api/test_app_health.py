from fastapi.testclient import TestClient

from resume_agent.api.app import create_app


def _client(**kw):
    return TestClient(create_app(db_url="sqlite://", **kw))


def test_health_ok():
    resp = _client().get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_no_auth_by_default():
    assert _client().get("/api/health").status_code == 200


def test_bearer_required_when_token_set():
    client = _client(api_token="secret")
    assert client.get("/api/health").status_code == 200  # health is unguarded
    # a guarded route (added later) would 401; here we assert the dep itself:
    import pytest

    from resume_agent.api.deps import require_token
    from resume_agent.api.errors import ApiException
    with pytest.raises(ApiException) as ei:
        require_token(authorization=None, settings=type("S", (), {"api_token": "secret"})())  # type: ignore[arg-type]
    assert ei.value.status_code == 401
