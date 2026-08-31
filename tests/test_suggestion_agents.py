from resume_tailor_harness.suggestions.agents import (
    ProjectIdea,
    RepoRef,
    SuggestionDraft,
    build_formatter_agent,
    build_search_agent,
)


def test_suggestion_draft_defaults():
    draft = SuggestionDraft()

    assert draft.repos == []
    assert draft.resources == []
    assert draft.project is None
    assert draft.bridge == ""
    assert draft.citations == []


def test_suggestion_draft_roundtrips_nested_models():
    draft = SuggestionDraft(
        repos=[
            RepoRef(
                name="kubernetes/kubernetes",
                url="https://github.com/kubernetes/kubernetes",
                why="Reference implementation",
            )
        ],
        project=ProjectIdea(
            title="Mini Kubernetes",
            summary="Build a scheduler",
            skills_demonstrated=["Go"],
        ),
        bridge="You know Docker, so this is a short jump.",
        citations=["https://kubernetes.io"],
    )

    assert draft.repos[0].name == "kubernetes/kubernetes"
    assert draft.project is not None
    assert draft.project.skills_demonstrated == ["Go"]


def test_builders_return_runners(monkeypatch):
    import resume_tailor_harness.suggestions.agents as agents_module

    monkeypatch.setattr(
        agents_module,
        "build_search_equipped",
        lambda *_args, **_kwargs: (object(), []),
    )
    monkeypatch.setattr(
        agents_module, "build_model", lambda *_args, **_kwargs: object()
    )
    monkeypatch.setattr(agents_module, "Agent", lambda **_kwargs: object())

    assert hasattr(build_search_agent(), "run")
    assert hasattr(build_formatter_agent(), "run")
