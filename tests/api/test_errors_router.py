from fastapi.testclient import TestClient
from sqlmodel import Session

from resume_agent.api.app import create_app
from resume_agent.services.errors import record_error


def _client(tmp_path):
    env = tmp_path / "empty.env"
    env.write_text("", encoding="utf-8")
    return TestClient(
        create_app(
            db_url="sqlite://",
            data_dir=tmp_path / "data",
            config_dir=tmp_path / "config",
            env_path=env,
            api_token="",
        )
    )


def _seed_record(client, *, source_label="pull") -> int:
    with Session(client.app.state.engine) as database:
        record = record_error(
            database,
            kind="run",
            source_label=source_label,
            message="boom",
        )
        assert record.id is not None
        return record.id


def test_error_list_defaults_to_open_records(tmp_path):
    with _client(tmp_path) as client:
        _seed_record(client)
        response = client.get("/api/errors")

    assert response.status_code == 200
    assert response.json()["records"][0] | {
        "firstSeenAt": "ignored",
        "lastSeenAt": "ignored",
        "updatedAt": "ignored",
    } == {
        "id": 1,
        "kind": "run",
        "sourceLabel": "pull",
        "runId": None,
        "message": "boom",
        "status": "open",
        "count": 1,
        "firstSeenAt": "ignored",
        "lastSeenAt": "ignored",
        "updatedAt": "ignored",
        "jobDetails": None,
    }
    pagination = response.json()["pagination"]
    assert pagination == {
        "page": 1, "pageSize": 50, "totalItems": 1, "totalPages": 1
    }


def test_dismiss_resolve_conflicts_and_unknown_ids(tmp_path):
    with _client(tmp_path) as client:
        record_id = _seed_record(client)
        dismissed = client.post(f"/api/errors/{record_id}/dismiss")
        conflict = client.post(f"/api/errors/{record_id}/resolve")
        missing = client.post("/api/errors/999/dismiss")

    assert dismissed.json()["status"] == "dismissed"
    assert conflict.status_code == 409
    assert missing.status_code == 404


def test_dismiss_all_and_invalid_status(tmp_path):
    with _client(tmp_path) as client:
        _seed_record(client, source_label="pull")
        _seed_record(client, source_label="tailor")
        cleared = client.post("/api/errors/dismiss-all")
        empty = client.get("/api/errors")
        invalid = client.get("/api/errors", params={"status": "weird"})

    assert cleared.json() == {"dismissed": 2}
    assert empty.json()["records"] == []
    assert invalid.status_code == 422
