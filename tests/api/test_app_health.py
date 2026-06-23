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
    with client:
        assert client.get("/api/health").status_code == 200  # health is unguarded
        assert client.get("/api/pipeline").status_code == 401
        assert client.get("/api/pipeline?token=secret").status_code == 200
