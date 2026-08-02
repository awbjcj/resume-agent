"""Career Lab orchestration tests cover commit and cancellation boundaries."""

from pathlib import Path
from types import SimpleNamespace
from typing import TypedDict

import pytest

from resume_agent.career_lab.models import CareerLabContextRefs
from resume_agent.career_lab.store import create_session, load_session
from resume_agent.career_skills.models import AgentFamily, AgentRunMeta
from resume_agent.career_skills.registry import CareerSkillRegistry
from resume_agent.services import career_lab
from resume_agent.sessions.stream import NullSink


class _Reporter:
    def __init__(self, *, cancel=False):
        self.cancel = cancel

    def begin(self, *_args, **_kwargs):
        return None

    def step(self, *_args, **_kwargs):
        return None

    def checkpoint(self):
        if self.cancel:
            raise RuntimeError("cancelled")


class _Response:
    def __init__(self, content: object) -> None:
        self.content = content


class _Persona:
    def __init__(self, meta: AgentRunMeta) -> None:
        self.run_meta = meta

    def run(self, prompt: str) -> _Response:
        return _Response("Use the offer data to prepare a careful draft.")

    async def arun(self, prompt: str) -> _Response:
        return self.run(prompt)


class _Formatter:
    def __init__(self, *, reject: bool = False) -> None:
        self.reject = reject

    def run(self, prompt: str) -> _Response:
        if self.reject:
            return _Response(SimpleNamespace(
                artifact_type="offer_comparison", title="", summary=""
            ))
        from resume_agent.career_lab.models import CareerLabArtifactMeta

        return _Response(CareerLabArtifactMeta(
            artifact_type="offer_comparison",
            title="Offer comparison",
            summary="Review base, equity, and downside risk.",
        ))

    async def arun(self, prompt: str) -> _Response:
        return self.run(prompt)


class _TurnKwargs(TypedDict):
    reporter: _Reporter
    root: Path
    engine: None
    message: str
    goal: str
    skill: str
    context_refs: CareerLabContextRefs
    sink: NullSink
    registry: CareerSkillRegistry
    persona_agent: _Persona
    formatter_agent: _Formatter


def _skill():
    return CareerSkillRegistry.from_paths("skills", "skills-lock.json").require(
        "salary-negotiation-prep", family=AgentFamily.CAREER_LAB, use="career_lab"
    )


def _meta(skill):
    return AgentRunMeta(
        agent_family=AgentFamily.CAREER_LAB,
        prompt_policy_version="career-lab-persona-v1",
        model_id="test-model",
        skill_ref=skill.ref,
    )


def _turn_kwargs(
    tmp_path: Path, *, reporter: _Reporter | None = None, formatter: _Formatter | None = None
) -> _TurnKwargs:
    skill = _skill()
    return {
        "reporter": reporter or _Reporter(),
        "root": tmp_path,
        "engine": None,
        "message": "Compare my offers.",
        "goal": "Prepare negotiation points",
        "skill": "salary-negotiation-prep",
        "context_refs": CareerLabContextRefs(offer_application_ids=[7]),
        "sink": NullSink(),
        "registry": CareerSkillRegistry.from_paths("skills", "skills-lock.json"),
        "persona_agent": _Persona(_meta(skill)),
        "formatter_agent": formatter or _Formatter(),
    }


def test_start_turn_persists_user_and_assistant_only_after_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(career_lab, "get_settings", lambda: SimpleNamespace(stream_enabled=False))
    result = career_lab.run_start_turn(**_turn_kwargs(tmp_path))
    session = load_session(tmp_path, result["sessionId"])
    assert [turn["role"] for turn in session["turns"]] == ["user", "assistant"]
    assert session["turns"][1]["skill_ref"]["name"] == "salary-negotiation-prep"
    assert session["turns"][1]["agent_meta"]["model_id"] == "test-model"


def test_formatter_retry_exhaustion_degrades_to_visible_persona(tmp_path, monkeypatch):
    monkeypatch.setattr(career_lab, "get_settings", lambda: SimpleNamespace(stream_enabled=False))
    result = career_lab.run_start_turn(
        **_turn_kwargs(tmp_path, formatter=_Formatter(reject=True))
    )
    session = load_session(tmp_path, result["sessionId"])
    assistant = session["turns"][1]
    assert assistant["text"].startswith("Use the offer data")
    assert assistant["notice"]
    assert assistant["artifact"] is None


def test_cancel_before_commit_keeps_transcript_byte_identical(tmp_path, monkeypatch):
    monkeypatch.setattr(career_lab, "get_settings", lambda: SimpleNamespace(stream_enabled=False))
    create_session(tmp_path, session_id="s1")
    path = tmp_path / "session-s1.json"
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match="cancelled"):
        career_lab.run_message_turn(
            reporter=_Reporter(cancel=True),
            root=tmp_path,
            engine=None,
            session_id="s1",
            message="draft this",
            skill="salary-negotiation-prep",
            context_refs=CareerLabContextRefs(),
            sink=NullSink(),
            registry=CareerSkillRegistry.from_paths("skills", "skills-lock.json"),
            persona_agent=_Persona(_meta(_skill())),
            formatter_agent=_Formatter(),
        )
    assert path.read_bytes() == before
