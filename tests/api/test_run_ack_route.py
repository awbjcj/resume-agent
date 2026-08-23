"""The run acknowledgement endpoint.

Ack is how a completion stops being announced again on the next reconnect. It is
deliberately forgiving: the client is reporting what it displayed, and a batch
that has gone partly stale is normal, so unusable ids are skipped rather than
failing the whole request.
"""

from concurrent.futures import Executor, Future

from fastapi.testclient import TestClient

from resume_agent.api.app import create_app


class InlineExecutor(Executor):
    def submit(self, fn, /, *args, **kwargs):
        future: Future = Future()
        future.set_result(fn(*args, **kwargs))
        return future


def _app(tmp_path):
    return create_app(
        db_url="sqlite://", run_executor=InlineExecutor(), runs_root=tmp_path
    )


def test_ack_stamps_terminal_runs_and_removes_them_from_the_listing(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        run_id = app.state.run_manager.submit("tailor", lambda reporter: {"ok": True})

        listed = client.get("/api/runs").json()["data"]
        assert [item["runId"] for item in listed] == [run_id]
        assert listed[0]["announcedAt"] is None

        response = client.post("/api/runs/ack", json={"runIds": [run_id]})
        assert response.status_code == 200
        assert response.json() == {"acknowledged": 1}

        assert client.get("/api/runs").json()["data"] == []
        assert client.get(f"/api/runs/{run_id}").json()["announcedAt"] is not None


def test_ack_is_idempotent_and_skips_unusable_ids(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        run_id = app.state.run_manager.submit("tailor", lambda reporter: {"ok": True})
        pending = app.state.run_manager.create("tailor")

        first = client.post("/api/runs/ack", json={"runIds": [run_id]})
        assert first.json() == {"acknowledged": 1}

        second = client.post(
            "/api/runs/ack", json={"runIds": [run_id, pending, "no-such-run"]}
        )
        assert second.status_code == 200
        assert second.json() == {"acknowledged": 0}


def test_ack_accepts_an_empty_list(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/runs/ack", json={"runIds": []})
        assert response.status_code == 200
        assert response.json() == {"acknowledged": 0}


def test_ack_skips_another_users_run(mu_app, mu_client):
    """Ownership is enforced per id, and a foreign id is skipped, not raised.

    The client is reporting what it displayed; failing the whole request over
    one id it should not have would make it re-announce every completion in the
    batch. Skipping leaks nothing -- the count simply does not include it.

    Runs in hosted mode deliberately: single-tenant has no ``UserContext``, so
    ``current_context()`` is None and no owner filtering applies there at all --
    the same contract ``_owned_record`` already has.
    """
    from sqlalchemy.orm import Session

    from resume_agent.api.auth import hash_password
    from resume_agent.tenancy.system_db import User
    from resume_agent.tenancy.workspace import provision_workspace

    with Session(mu_app.state.system_engine) as session:
        session.add(
            User(
                id="stranger0000",
                username="stranger",
                password_hash=hash_password("stranger-password"),
                role="user",
            )
        )
        session.commit()
    provision_workspace(
        mu_app.state.data_dir,
        "stranger0000",
        template_dir=mu_app.state.template_config_dir,
    )

    manager = mu_app.state.run_manager
    foreign = manager.create("tailor", user_id="stranger0000")
    manager.reporter(foreign, "tailor").done(result={"ok": True})
    assert manager.get(foreign).state.value == "done"

    assert (
        mu_client.post(
            "/api/auth/login",
            json={"identifier": "owner", "password": "owner-password"},
        ).status_code
        == 200
    )

    response = mu_client.post("/api/runs/ack", json={"runIds": [foreign]})

    assert response.status_code == 200
    assert response.json() == {"acknowledged": 0}
    assert manager.get(foreign).announced_at is None
