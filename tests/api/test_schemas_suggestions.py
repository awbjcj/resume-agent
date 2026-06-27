from datetime import datetime, timezone

from resume_agent.api.schemas.suggestions import SuggestionEnvelope, SuggestionOut


def test_suggestion_out_camelizes_nested_fields():
    suggestion = SuggestionOut(
        kind="skill",
        key="Kubernetes",
        repos=[
            {
                "name": "foo/bar",
                "url": "https://github.com/foo/bar",
                "why": "Reference",
                "stars": 3,
                "description": "Repository",
            }
        ],
        resources=[
            {"title": "Documentation", "url": "https://example.com/docs", "kind": "doc"}
        ],
        project={
            "title": "Project",
            "summary": "Build it",
            "skills_demonstrated": ["Go"],
        },
        bridge="Bridge",
        citations=["https://example.com/docs"],
        generated_at=datetime(2026, 6, 26, tzinfo=timezone.utc),
    )

    dumped = suggestion.model_dump(by_alias=True)

    assert dumped["project"]["skillsDemonstrated"] == ["Go"]
    assert "generatedAt" in dumped


def test_suggestion_envelope_allows_empty_cache():
    envelope = SuggestionEnvelope(suggestion=None, stale=False)

    assert envelope.model_dump(by_alias=True) == {"suggestion": None, "stale": False}
