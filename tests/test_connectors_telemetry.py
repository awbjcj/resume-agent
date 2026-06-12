from resume_agent.discovery.connectors.telemetry import read_runs, record_run


def test_read_runs_missing_file_returns_empty(tmp_path):
    assert read_runs(tmp_path / "none.json") == {}


def test_record_run_persists_and_roundtrips(tmp_path):
    path = tmp_path / "runs.json"
    record_run(path, "greenhouse", added=4, error=None)
    record_run(path, "adzuna", added=0, error="HTTP 429")

    runs = read_runs(path)
    assert runs["greenhouse"]["added"] == 4
    assert runs["greenhouse"]["error"] is None
    assert runs["greenhouse"]["last_run"]
    assert runs["adzuna"]["error"] == "HTTP 429"


def test_record_run_overwrites_previous_entry_for_same_source(tmp_path):
    path = tmp_path / "runs.json"
    record_run(path, "greenhouse", added=4, error=None)
    record_run(path, "greenhouse", added=9, error=None)
    assert read_runs(path)["greenhouse"]["added"] == 9
