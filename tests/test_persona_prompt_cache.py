from types import SimpleNamespace

from resume_tailor_harness.discovery import scout
from resume_tailor_harness.interview import agent as interview
from resume_tailor_harness.profile import coach


def _cache_enabled(runner) -> bool:
    return bool(getattr(runner._agent.model, "cache_system_prompt", False))


def test_persona_builders_enable_anthropic_system_prompt_cache(monkeypatch):
    settings = SimpleNamespace(
        mid_model="claude-sonnet-5", cheap_model="claude-haiku-4-5"
    )
    monkeypatch.setattr(coach, "get_settings", lambda: settings)
    monkeypatch.setattr(interview, "get_settings", lambda: settings)
    assert _cache_enabled(coach.build_coach_agent([]))
    assert _cache_enabled(interview.build_interviewer_agent(interview.InterviewStyle()))


def test_formatter_builders_enable_anthropic_system_prompt_cache(monkeypatch):
    settings = SimpleNamespace(
        mid_model="claude-sonnet-5", cheap_model="claude-haiku-4-5"
    )
    monkeypatch.setattr(coach, "get_settings", lambda: settings)
    monkeypatch.setattr(interview, "get_settings", lambda: settings)
    monkeypatch.setattr(scout, "get_settings", lambda: settings)
    assert _cache_enabled(coach.build_coach_formatter_agent(coach.CoachTurn))
    assert _cache_enabled(
        interview.build_interview_formatter_agent(interview.InterviewTurn)
    )
    assert _cache_enabled(scout.build_scout_formatter_agent())
