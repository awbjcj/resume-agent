from datetime import datetime, timezone

import pytest
from pydantic import AnyHttpUrl, TypeAdapter, ValidationError

from resume_agent.api.schemas.suggestions import (
    ProjectOut,
    RepoOut,
    ResourceOut,
    SuggestionEnvelope,
    SuggestionRunAcceptedOut,
    SuggestionRunNotFoundOut,
    SuggestionRunsOut,
    SuggestionRunsRequest,
    SuggestionOut,
    SuggestionTarget,
)

_http_url = TypeAdapter(AnyHttpUrl).validate_python


def test_suggestion_out_camelizes_nested_fields():
    suggestion = SuggestionOut(
        kind="skill",
        key="Kubernetes",
        repos=[
            RepoOut(
                name="foo/bar",
                url=_http_url("https://github.com/foo/bar"),
                why="Reference",
                stars=3,
                description="Repository",
            )
        ],
        resources=[
            ResourceOut(
                title="Documentation",
                url=_http_url("https://example.com/docs"),
                kind="doc",
            )
        ],
        project=ProjectOut(
            title="Project",
            summary="Build it",
            skills_demonstrated=["Go"],
        ),
        bridge="Bridge",
        citations=[_http_url("https://example.com/docs")],
        generated_at=datetime(2026, 6, 26, tzinfo=timezone.utc),
    )

    dumped = suggestion.model_dump(by_alias=True)

    assert dumped["project"]["skillsDemonstrated"] == ["Go"]
    assert "generatedAt" in dumped


def test_suggestion_envelope_allows_empty_cache():
    envelope = SuggestionEnvelope(suggestion=None, stale=False)

    assert envelope.model_dump(by_alias=True) == {"suggestion": None, "stale": False}


def test_suggestion_runs_request_trims_keys_and_forbids_extra_context():
    request = SuggestionRunsRequest(targets=[SuggestionTarget(kind="skill", key="  python  ")])

    assert request.targets[0].key == "python"
    with pytest.raises(ValidationError):
        SuggestionRunsRequest.model_validate(
            {"targets": [{"kind": "skill", "key": "python", "members": ["unsafe"]}]}
        )


def test_suggestion_runs_response_is_discriminated_and_camelized():
    response = SuggestionRunsOut(
        results=[
            SuggestionRunAcceptedOut(
                outcome="accepted",
                kind="skill",
                key="python",
                run_id="r1",
            ),
            SuggestionRunNotFoundOut(
                outcome="not_found",
                kind="theme",
                key="missing",
            ),
        ]
    )

    assert response.model_dump(by_alias=True) == {
        "results": [
            {
                "outcome": "accepted",
                "kind": "skill",
                "key": "python",
                "runId": "r1",
            },
            {"outcome": "not_found", "kind": "theme", "key": "missing"},
        ]
    }
