def test_search_suggestions_model_roundtrips():
    from resume_agent.discovery.search_scout import SearchSuggestion, SearchSuggestions

    report = SearchSuggestions(
        suggestions=[
            SearchSuggestion(value="Rust", kind="keyword", reason="profile uses Rust")
        ]
    )
    assert report.suggestions[0].kind == "keyword"
    assert report.suggestions[0].value == "Rust"


def test_builders_wire_models_and_schema(monkeypatch):
    from resume_agent.config import Settings
    from resume_agent.discovery import search_scout

    captured: dict = {}

    def fake_agent(**kwargs):
        captured.clear()
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(search_scout, "Agent", fake_agent)
    monkeypatch.setattr(search_scout, "AgentRunner", lambda agent: agent)
    monkeypatch.setattr(
        search_scout,
        "get_settings",
        lambda: Settings.model_construct(
            mid_model="anthropic:mid", cheap_model="anthropic:cheap"
        ),
    )
    monkeypatch.setattr(
        search_scout,
        "build_search_equipped",
        lambda model_id, **_kwargs: (model_id, ["tool"]),
    )
    monkeypatch.setattr(search_scout, "build_model", lambda model_id: model_id)
    monkeypatch.setattr(search_scout, "use_json_mode_for", lambda model: True)

    assert search_scout.build_search_scout_research_agent() is not None
    assert captured["model"] == "anthropic:mid"

    assert search_scout.build_search_scout_formatter_agent() is not None
    assert captured["model"] == "anthropic:cheap"
    assert captured["output_schema"] is search_scout.SearchSuggestions


def test_registry_exposes_search_scout_specs():
    from resume_agent.prompts.registry import spec_for

    assert spec_for("search-scout-research") is not None
    assert spec_for("search-scout-format") is not None
