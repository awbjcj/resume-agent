import time

from fastapi.testclient import TestClient

import resume_agent.api.routers.match_gap as router_mod
import resume_agent.tracking.canonicalize as canonicalize
from resume_agent.api.app import create_app
from resume_agent.db import get_session
from resume_agent.tracking.repository import save_job
from resume_agent.tracking.tables import Job, JobStatus


def test_refresh_clusters_run_completes(monkeypatch, tmp_path):
    monkeypatch.setattr(
        canonicalize,
        "build_skill_canonicalizer",
        lambda: (lambda tokens: {token: token for token in tokens}),
    )
    monkeypatch.setattr(
        canonicalize,
        "build_skill_themer",
        lambda: (
            lambda tokens: [
                ("Cloud / Infrastructure", ["k8s"]),
                ("Frontend", ["react"]),
            ]
        ),
    )
    monkeypatch.setattr(router_mod, "_CLUSTER_PATH", str(tmp_path / "cluster_map.json"))

    app = create_app(db_url="sqlite://")
    with TestClient(app) as client:
        with get_session(app.state.engine) as session:
            save_job(
                session,
                Job(
                    source="manual",
                    company="C",
                    title="T",
                    status=JobStatus.shortlisted.value,
                    criteria_json={"must_have_skills": ["k8s", "React"]},
                ),
            )

        response = client.post("/api/match-gap/refresh-clusters")
        assert response.status_code == 202
        run_id = response.json()["runId"]

        for _ in range(50):
            record = client.get(f"/api/runs/{run_id}").json()
            if record["state"] in ("done", "error"):
                break
            time.sleep(0.02)

    assert record["state"] == "done"
    assert record["result"] == {"skills": 2, "themes": 2}
