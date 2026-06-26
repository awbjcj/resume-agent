import json
from pathlib import Path

from resume_agent.api.app import create_app

CONTRACT = Path("contracts/openapi.json")


def test_openapi_exposes_core_paths():
    spec = create_app(db_url="sqlite://").openapi()
    paths = spec["paths"]
    for p in ("/api/shortlist", "/api/pipeline", "/api/triage", "/api/jobs/{job_id}",
              "/api/discover", "/api/reprocess", "/api/refresh",
              "/api/runs/{run_id}", "/api/runs/{run_id}/events", "/api/sources"):
        assert p in paths, f"missing {p}"


def test_committed_openapi_is_current():
    """The committed contract must match the live app — regenerate if this fails."""
    assert CONTRACT.exists(), "run scripts/export_openapi.py and commit contracts/openapi.json"
    live = create_app(db_url="sqlite://").openapi()
    committed = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert committed == live, "contracts/openapi.json is stale — re-run scripts/export_openapi.py"
