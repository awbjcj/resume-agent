from resume_agent.discovery import search_scout, source_scout
from resume_agent.llm_runner import build_model


def test_search_research_prompt_lists_every_supported_kind():
    instructions = "\n".join(search_scout._RESEARCH_INSTRUCTIONS)

    assert (
        "keyword/title/role_anchor/exclude_term/location/seniority/adjacent_role"
        in instructions
    )


def test_source_research_agent_forwards_capabilities(monkeypatch):
    captured = {}

    def fake_build(model_id, mode=None, *, reasoning=False, cache_system_prompt=False):
        captured.update(reasoning=reasoning, cache=cache_system_prompt)
        return build_model("claude-haiku-4-5-20251001", api_key="k"), []

    monkeypatch.setattr(source_scout, "build_search_equipped", fake_build)
    source_scout.build_scout_research_agent(lambda _url: "{}")
    assert captured == {"reasoning": True, "cache": True}


def test_search_research_agent_forwards_capabilities(monkeypatch):
    captured = {}

    def fake_build(model_id, mode=None, *, reasoning=False, cache_system_prompt=False):
        captured.update(reasoning=reasoning, cache=cache_system_prompt)
        return build_model("claude-haiku-4-5-20251001", api_key="k"), []

    monkeypatch.setattr(search_scout, "build_search_equipped", fake_build)
    search_scout.build_search_scout_research_agent()
    assert captured == {"reasoning": True, "cache": True}
