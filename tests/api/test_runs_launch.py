import time
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlmodel import Session

from resume_tailor_harness.api.app import create_app
from resume_tailor_harness.api.routers import runs as runs_router
from resume_tailor_harness.progress import ProgressReporter
from resume_tailor_harness.services.errors import list_error_records


def _wait_for_run_done(client: TestClient, run_id: str, *, timeout: float = 5) -> None:
    # Lifespan shutdown disposes the app's DB engine right after the `with
    # client:` block exits. A run's terminal callback writes to that engine
    # from its own executor thread, so the test must not let the block exit
    # until the run has actually reached a terminal state — otherwise engine
    # disposal can race that write (RuntimeError: Set changed size during
    # iteration in SQLAlchemy's pool teardown).
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if client.get(f"/api/runs/{run_id}").json()["state"] == "done":
            return
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} did not reach state 'done' in time")


class InlineExecutor(Executor):
    def submit(self, fn, /, *args, **kwargs):
        fut: Future = Future()
        try:
            fut.set_result(fn(*args, **kwargs))
        except Exception as exc:  # noqa: BLE001
            fut.set_exception(exc)
        return fut


def _client(tmp_path):
    env = tmp_path / ".env"
    env.write_text("", encoding="utf-8")
    return TestClient(
        create_app(
            db_url="sqlite://",
            run_executor=InlineExecutor(),
            runs_root=tmp_path,
            env_path=env,
        )
    )


def test_discover_launch_returns_run(monkeypatch, tmp_path):
    # Fake the service so no LLM/network runs; assert the run wiring works.
    def fake_discover_jobs(session, *, reporter=None, **kw):
        reporter.begin(1, "x")  # type: ignore[attr-defined]
        reporter.step(1)  # type: ignore[attr-defined]
        return {"shortlisted": 2}

    monkeypatch.setattr(runs_router, "discover_jobs", fake_discover_jobs)
    client = _client(tmp_path)
    with client:
        resp = client.post("/api/discover", json={})
        assert resp.status_code == 202
        run_id = resp.json()["runId"]
        got = client.get(f"/api/runs/{run_id}").json()
    assert got["kind"] == "discover"
    assert got["state"] == "done"
    assert got["result"] == {"statusCounts": {"shortlisted": 2}}
    assert got["percent"] == 100


def test_get_unknown_run_404(tmp_path):
    client = _client(tmp_path)
    with client:
        assert client.get("/api/runs/deadbeef").status_code == 404


def test_resume_revise_launches_a_durable_artifact_run(monkeypatch, tmp_path):
    monkeypatch.setattr(
        runs_router,
        "get_resume_version",
        lambda _session, version_id: SimpleNamespace(id=version_id, job_id=3),
    )
    monkeypatch.setattr(
        runs_router,
        "revise_resume_version",
        lambda _session, _version_id, _instruction, **_kw: SimpleNamespace(
            id=42, job_id=3
        ),
    )
    with _client(tmp_path) as client:
        response = client.post(
            "/api/resume-versions/5/revise",
            json={"instruction": "shorter", "reReview": False},
        )
        assert response.status_code == 202
        run = client.get(f"/api/runs/{response.json()['runId']}").json()
    assert run["kind"] == "revise"
    assert run["meta"] == {
        "versionId": 5,
        "jobId": 3,
        "instruction": "shorter",
        "reReview": False,
    }
    assert run["result"] == {"versionId": 42, "jobId": 3}


def test_cover_letter_revise_launches_a_durable_artifact_run(monkeypatch, tmp_path):
    monkeypatch.setattr(
        runs_router,
        "get_cover_letter",
        lambda _session, cover_id: SimpleNamespace(id=cover_id, job_id=8),
    )
    monkeypatch.setattr(
        runs_router,
        "revise_cover_letter_version",
        lambda _session, _cover_id, _instruction, **_kw: SimpleNamespace(
            id=77, job_id=8
        ),
    )
    with _client(tmp_path) as client:
        response = client.post(
            "/api/cover-letters/5/revise",
            json={"instruction": "warmer", "reReview": False},
        )
        assert response.status_code == 202
        run = client.get(f"/api/runs/{response.json()['runId']}").json()
    assert run["kind"] == "coverLetterRevise"
    assert run["meta"] == {"coverLetterId": 5, "jobId": 8, "instruction": "warmer"}
    assert run["result"] == {"coverLetterId": 77, "jobId": 8}


def test_duplicate_resume_revise_returns_conflict_with_active_run(
    monkeypatch, tmp_path
):
    started = Event()
    release = Event()
    executor = ThreadPoolExecutor(max_workers=1)
    env = tmp_path / ".env"
    env.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        runs_router,
        "get_resume_version",
        lambda _session, version_id: SimpleNamespace(id=version_id, job_id=3),
    )

    def wait_to_revise(*_args, **_kwargs):
        started.set()
        assert release.wait(timeout=5)
        return SimpleNamespace(id=42, job_id=3)

    monkeypatch.setattr(runs_router, "revise_resume_version", wait_to_revise)
    client = TestClient(
        create_app(
            db_url="sqlite://",
            run_executor=executor,
            runs_root=tmp_path,
            env_path=env,
        )
    )

    try:
        with client:
            first = client.post(
                "/api/resume-versions/5/revise",
                json={"instruction": "shorter", "reReview": False},
            )
            assert first.status_code == 202
            assert started.wait(timeout=5)

            duplicate = client.post(
                "/api/resume-versions/5/revise",
                json={"instruction": "warmer", "reReview": False},
            )

            assert duplicate.status_code == 409
            assert duplicate.json()["error"] == {
                "code": "CONFLICT",
                "message": "A revision is already running for this item",
                "details": {"runId": first.json()["runId"]},
            }
            release.set()
            _wait_for_run_done(client, first.json()["runId"])
    finally:
        release.set()
        executor.shutdown(wait=True)


def test_tailor_launch_passes_params(monkeypatch, tmp_path):
    captured = {}

    def fake_tailor(session, *, job_ids=None, approved=False, reporter=None, **kw):
        captured["job_ids"] = job_ids
        captured["approved"] = approved
        captured["fail_on_partial"] = kw.get("fail_on_partial")
        reporter.begin(1, "x")  # type: ignore[attr-defined]
        reporter.step(1)  # type: ignore[attr-defined]
        return {}

    monkeypatch.setattr(runs_router, "tailor", fake_tailor)
    client = _client(tmp_path)
    with client:
        client.post("/api/tailor", json={"jobIds": [1, 2], "approved": False})
    assert captured["job_ids"] == [1, 2]
    assert captured["fail_on_partial"] is True


def test_tailor_launch_maps_deep_to_review_path(monkeypatch, tmp_path):
    review_paths = []

    def fake_tailor(session, *, reporter=None, **kwargs):
        review_paths.append(kwargs["review_path"])
        reporter.begin(1, "x")  # type: ignore[attr-defined]
        reporter.step(1)  # type: ignore[attr-defined]
        return {}

    monkeypatch.setattr(runs_router, "tailor", fake_tailor)
    client = _client(tmp_path)
    with client:
        client.post("/api/tailor", json={"approved": True, "deep": True})
        client.post("/api/tailor", json={"approved": True})

    assert review_paths == ["config/review_deep.yaml", "config/review.yaml"]


def test_cover_letter_launch_persists_resolved_targets(monkeypatch, tmp_path):
    monkeypatch.setattr(
        runs_router,
        "resolve_cover_letter_targets",
        lambda _session, **_kwargs: [SimpleNamespace(id=4), SimpleNamespace(id=9)],
    )
    captured = {}

    def fake_write(_session, *, job_ids, approved, reporter, **_kwargs):
        captured.update(job_ids=job_ids, approved=approved)
        reporter.begin(2, "Starting")
        reporter.step(2)
        return []

    monkeypatch.setattr(runs_router, "write_cover_letters", fake_write)

    with _client(tmp_path) as client:
        response = client.post("/api/cover-letters", json={"approved": True})
        run = client.get(f"/api/runs/{response.json()['runId']}").json()

    assert response.status_code == 202
    assert response.json()["meta"] == {"jobIds": [4, 9]}
    assert run["meta"] == {"jobIds": [4, 9]}
    assert captured == {"job_ids": [4, 9], "approved": False}


def test_cover_letter_launch_rejects_overlapping_active_jobs(monkeypatch, tmp_path):
    started = Event()
    release = Event()
    executor = ThreadPoolExecutor(max_workers=2)
    env = tmp_path / ".env"
    env.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        runs_router,
        "resolve_cover_letter_targets",
        lambda _session, *, job_ids, approved: [
            SimpleNamespace(id=job_id) for job_id in (job_ids or [])
        ],
    )

    def wait_to_write(_session, *, reporter, **_kwargs):
        reporter.begin(1, "Starting")
        started.set()
        assert release.wait(timeout=5)
        reporter.step(1)
        return []

    monkeypatch.setattr(runs_router, "write_cover_letters", wait_to_write)
    client = TestClient(
        create_app(
            db_url="sqlite://",
            run_executor=executor,
            runs_root=tmp_path,
            env_path=env,
        )
    )

    try:
        with client:
            first = client.post(
                "/api/cover-letters", json={"jobIds": [1, 2], "approved": False}
            )
            assert first.status_code == 202
            assert started.wait(timeout=5)

            duplicate = client.post(
                "/api/cover-letters", json={"jobIds": [2, 3], "approved": False}
            )

            assert duplicate.status_code == 409
            assert duplicate.json()["error"]["details"] == {
                "runId": first.json()["runId"]
            }
            release.set()
            _wait_for_run_done(client, first.json()["runId"])
    finally:
        release.set()
        executor.shutdown(wait=True)


def test_reprocess_endpoint_launches_run(monkeypatch, tmp_path):
    def fake_reprocess_jobs(session, *, scopes, reporter=None, **kw):
        return {"shortlisted": 1}

    monkeypatch.setattr(runs_router, "reprocess_jobs", fake_reprocess_jobs)
    client = _client(tmp_path)
    with client:
        resp = client.post("/api/reprocess", json={"scopes": ["shortlisted"]})
    assert resp.status_code == 202
    assert resp.json()["kind"] == "reprocess"


def test_refresh_endpoint_launches_run(monkeypatch, tmp_path):
    from resume_tailor_harness.services.discovery import RefreshReport

    def fake_refresh_jobs(session, *, limit=None, reporter=None, **kw):
        return RefreshReport(pulled=0, totals={}, status_counts={}, failures={})

    monkeypatch.setattr(runs_router, "refresh_jobs", fake_refresh_jobs)
    client = _client(tmp_path)
    with client:
        resp = client.post("/api/refresh", json={"limit": None})
    assert resp.status_code == 202
    assert resp.json()["kind"] == "refresh"


def test_pull_refresh_disables_skip_known(monkeypatch, tmp_path):
    captured = {}

    def fake_pull_jobs(session, **kwargs):
        from resume_tailor_harness.discovery.connectors.runner import PullReport

        captured.update(kwargs)
        return PullReport()

    monkeypatch.setattr(runs_router, "pull_jobs", fake_pull_jobs)
    client = _client(tmp_path)
    with client:
        response = client.post("/api/pull", json={"refresh": True})

    assert response.status_code == 202
    assert captured["skip_known"] is False


def test_pull_source_failures_are_recorded_with_the_run_id(monkeypatch, tmp_path):
    def fake_pull_jobs(_session, **_kwargs):
        from resume_tailor_harness.discovery.connectors.runner import PullReport

        return PullReport(
            failures={"companies": {"https://x.example": "detect failed"}}
        )

    monkeypatch.setattr(runs_router, "pull_jobs", fake_pull_jobs)
    client = _client(tmp_path)
    with client:
        response = client.post("/api/pull", json={})
        assert response.status_code == 202
        run_id = response.json()["runId"]
        with Session(client.app.state.engine) as database:  # type: ignore[union-attr]
            records = list_error_records(database)

    assert len(records) == 1
    assert records[0].source_label == "companies:https://x.example"
    assert records[0].run_id == run_id


def test_linkedin_scrape_launch_returns_run(monkeypatch, tmp_path):
    def fake_scrape(session, *, reporter: ProgressReporter | None = None, **kwargs):
        assert reporter is not None
        reporter.begin(1, "x")
        reporter.step(1)
        return {"added": 3, "failures": {}}

    monkeypatch.setattr(
        runs_router,
        "scrape_linkedin_jobs",
        fake_scrape,
        raising=False,
    )
    monkeypatch.setattr(runs_router, "_linkedin_ready", lambda: True, raising=False)
    client = _client(tmp_path)

    with client:
        response = client.post("/api/sources/linkedin/scrape")
        run_id = response.json()["runId"] if response.status_code == 202 else ""
        run = client.get(f"/api/runs/{run_id}").json() if run_id else {}

    assert response.status_code == 202
    assert run["kind"] == "linkedinScrape"
    assert run["state"] == "done"
    assert run["result"] == {"added": 3, "failures": {}}


def test_linkedin_scrape_409_when_not_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(runs_router, "_linkedin_ready", lambda: False, raising=False)
    client = _client(tmp_path)

    with client:
        response = client.post("/api/sources/linkedin/scrape")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "LINKEDIN_NOT_CONFIGURED"


def test_linkedin_ready_requires_credentials_or_nonempty_profile(monkeypatch, tmp_path):
    profile = tmp_path / "linkedin-profile"
    profile.mkdir()
    settings = SimpleNamespace(
        linkedin_email="",
        linkedin_password="",
        linkedin_user_data_dir=str(profile),
    )
    monkeypatch.setattr(runs_router, "get_settings", lambda: settings, raising=False)

    assert runs_router._linkedin_ready() is False

    (profile / "Local State").write_text("{}", encoding="utf-8")
    assert runs_router._linkedin_ready() is True


def test_linkedin_ready_rejects_regular_file(monkeypatch, tmp_path):
    profile_file = tmp_path / "linkedin-profile"
    profile_file.write_text("not a directory", encoding="utf-8")
    settings = SimpleNamespace(
        linkedin_email="",
        linkedin_password="",
        linkedin_user_data_dir=str(profile_file),
    )
    monkeypatch.setattr(runs_router, "get_settings", lambda: settings, raising=False)

    assert runs_router._linkedin_ready() is False


def test_linkedin_ready_false_when_browser_disabled(monkeypatch, tmp_path):
    """A saved profile or credentials never make LinkedIn ready without a browser."""
    profile = tmp_path / "linkedin-profile"
    profile.mkdir()
    (profile / "Local State").write_text("{}", encoding="utf-8")
    settings = SimpleNamespace(
        browser_enabled=False,
        linkedin_email="user@example.com",
        linkedin_password="secret",
        linkedin_user_data_dir=str(profile),
    )
    monkeypatch.setattr(runs_router, "get_settings", lambda: settings, raising=False)

    assert runs_router._linkedin_ready() is False


def test_import_urls_launch_isolates_failures(monkeypatch, tmp_path):
    def fake_add(session, *, url, **kw):
        if "bad" in url:
            raise ValueError("no reader for host")
        return SimpleNamespace(id=1)

    monkeypatch.setattr(runs_router, "add_job_from_url", fake_add)
    body = (
        b"https://ok.test/a\n# comment\n\nhttps://bad.test/b\n"
        b"not-a-url\nhttps://ok.test/c\n"
    )
    with _client(tmp_path) as client:
        response = client.post(
            "/api/jobs/import-urls",
            files={"file": ("urls.txt", body, "text/plain")},
        )
        assert response.status_code == 202
        run = client.get(f"/api/runs/{response.json()['runId']}").json()
    assert run["kind"] == "importUrls"
    assert run["result"]["added"] == 2
    assert "https://bad.test/b" in run["result"]["failures"]
    assert "not-a-url" in run["result"]["failures"]


def test_import_urls_rejects_empty_file(tmp_path):
    with _client(tmp_path) as client:
        response = client.post(
            "/api/jobs/import-urls",
            files={"file": ("urls.txt", b"# nothing\n", "text/plain")},
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "NO_URLS"
