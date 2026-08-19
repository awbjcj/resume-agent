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


def test_openapi_exposes_scout_source_verification_contract():
    spec = create_app(db_url="sqlite://").openapi()
    paths = spec["paths"]
    resolve = paths["/api/scout/sessions/{session_id}/proposals/{proposal_id}/resolve"]["post"]
    approve = paths["/api/scout/sessions/{session_id}/proposals/{proposal_id}/approve"]["post"]
    schemas = spec["components"]["schemas"]

    assert resolve["requestBody"]["required"] is True
    assert resolve["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ScoutResolveSourceIn"
    )
    assert approve["requestBody"].get("required", False) is False
    approve_variants = approve["requestBody"]["content"]["application/json"]["schema"]["anyOf"]
    assert any(variant.get("$ref", "").endswith("/ScoutApproveIn") for variant in approve_variants)
    assert "manualConfirmation" in schemas["ScoutProposalOut"]["properties"]
    assert "resolutionStatus" in schemas["ScoutSourceOut"]["properties"]
    assert "searchedFamilies" in schemas["ScoutSourceOut"]["properties"]
    assert "conflict" in schemas["ScoutProposalOut"]["properties"]["check"]["enum"]


def test_uccm_match_gap_metadata_is_additive_not_required():
    spec = create_app(db_url="sqlite://").openapi()
    schema = spec["components"]["schemas"]["MatchGapOut"]
    required = set(schema.get("required", []))
    additive_fields = {
        "uccmState",
        "matchingPolicyRevision",
        "profileFactsRevision",
        "assertionPolicyRevision",
    }

    assert required.isdisjoint(additive_fields)
    assert all("default" not in schema["properties"][field] for field in additive_fields)


def test_committed_openapi_is_current():
    """The committed contract must match the live app — regenerate if this fails."""
    assert CONTRACT.exists(), "run scripts/export_openapi.py and commit contracts/openapi.json"
    live = create_app(db_url="sqlite://").openapi()
    committed = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert committed == live, "contracts/openapi.json is stale — re-run scripts/export_openapi.py"
