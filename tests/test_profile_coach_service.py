from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import pytest

from resume_agent.profile.coach import CoachTurn, DraftNote, NewTopic, OpeningTurn
from resume_agent.profile.coach_store import load_session
from resume_agent.services.profile_coach import (
    approve_draft,
    discard_draft,
    run_build_with_impact,
    run_message_turn,
    run_opening_turn,
    run_recap_turn,
    session_view,
    sessions_view,
)


class FakeReporter:
    process = "run-1"

    def begin(self, total, label, **extra):
        pass

    def step(self, current, *, label=None, **extra):
        pass

    def checkpoint(self):
        pass


@dataclass
class FakeResult:
    content: object


class FakeAgent:
    def __init__(self, *contents: object):
        self.contents = list(contents)
        self.prompts: list[str] = []

    def run(self, prompt: str) -> FakeResult:
        self.prompts.append(prompt)
        return FakeResult(self.contents.pop(0))

    async def arun(self, prompt: str) -> FakeResult:
        return self.run(prompt)


def _open(profile_dir):
    return run_opening_turn(
        FakeReporter(),
        profile_dir=profile_dir,
        coach_agent=FakeAgent("notes"),
        formatter_agent=FakeAgent(
            OpeningTurn(
                message="Welcome! What changed at Acme?",
                action="ask",
                topic_id="t1",
                topics=[NewTopic(gap="Acme impact"), NewTopic(gap="K8s evidence")],
            )
        ),
    )


def _seed_primary(profile_dir):
    from resume_agent.profile.corpus import add_source

    source = profile_dir.parent / "resume.txt"
    source.write_text("Resume body", encoding="utf-8")
    add_source(profile_dir, source, primary=True)


def _drafted_session(tmp_path):
    profile_dir = tmp_path / "profile"
    _seed_primary(profile_dir)
    sid = _open(profile_dir)["sessionId"]
    run_message_turn(
        FakeReporter(),
        profile_dir=profile_dir,
        session_id=sid,
        message="I cut deploy time from 40 min to 6 min.",
        coach_agent=FakeAgent("notes"),
        formatter_agent=FakeAgent(
            CoachTurn(
                message="Strong number. Draft ready.",
                action="draft",
                topic_id="t1",
                draft_note=DraftNote(
                    title="Acme deploys",
                    summary="Cut deploy time from 40 min to 6 min.",
                    quotes=["I cut deploy time from 40 min to 6 min."],
                ),
            )
        ),
    )
    return profile_dir, sid


def test_opening_and_message_turn_create_durable_views(tmp_path):
    view = _open(tmp_path)
    assert view["status"] == "active"
    assert sessions_view(tmp_path)["sessions"][0]["sessionId"] == view["sessionId"]
    updated = run_message_turn(
        FakeReporter(),
        profile_dir=tmp_path,
        session_id=view["sessionId"],
        message="I improved deploys.",
        coach_agent=FakeAgent("notes"),
        formatter_agent=FakeAgent(
            CoachTurn(message="How did you measure it?", action="ask", topic_id="t1")
        ),
    )
    assert updated["turns"][-2]["topicId"] == "t1"
    assert updated["turns"][-1]["kind"] == "question"


def test_formatter_retries_once_and_failed_turn_leaves_no_residue(tmp_path):
    sid = _open(tmp_path)["sessionId"]
    formatter = FakeAgent(
        CoachTurn(
            message="Draft.",
            action="draft",
            topic_id="t1",
            draft_note=DraftNote(title="T", summary="S", quotes=["fabricated"]),
        ),
        CoachTurn(message="How was it measured?", action="ask", topic_id="t1"),
    )
    run_message_turn(
        FakeReporter(),
        profile_dir=tmp_path,
        session_id=sid,
        message="We improved deploys.",
        coach_agent=FakeAgent("notes"),
        formatter_agent=formatter,
    )
    assert "fabricated quote" in formatter.prompts[1]
    before = len(load_session(tmp_path, sid)["turns"])
    with pytest.raises(Exception):
        run_message_turn(
            FakeReporter(),
            profile_dir=tmp_path,
            session_id=sid,
            message="again",
            coach_agent=FakeAgent("notes"),
            formatter_agent=FakeAgent(
                CoachTurn(message="", action="ask", topic_id="t1"),
                CoachTurn(message="", action="ask", topic_id="t1"),
            ),
        )
    assert len(load_session(tmp_path, sid)["turns"]) == before


def test_approval_requires_quote_and_is_exactly_once_under_concurrency(tmp_path):
    profile_dir, sid = _drafted_session(tmp_path)
    with pytest.raises(ValueError, match="quote"):
        approve_draft(
            profile_dir,
            sid,
            "t1",
            title="T",
            summary="S",
            quotes=[],
        )

    def approve():
        try:
            return approve_draft(
                profile_dir,
                sid,
                "t1",
                title="Acme deploys",
                summary="Cut deploy time from 40 min to 6 min.",
                quotes=["I cut deploy time from 40 min to 6 min."],
            )
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: approve(), range(2)))
    assert sum(not outcome.startswith("draft already") for outcome in outcomes) == 1
    from resume_agent.profile.corpus import load_manifest

    assert len(load_manifest(profile_dir).docs) == 2


def test_recap_without_user_input_ends_deterministically_and_skips_llm(tmp_path):
    # Ending a session the user never answered has no evidence to recap. Asking
    # the LLM to summarize an empty conversation yields an empty message that
    # normalize_recap rejects ("empty message"), surfacing as a run error. A
    # no-input session must close deterministically without touching the LLM.
    sid = _open(tmp_path)["sessionId"]

    class Boom:
        def run(self, prompt):
            raise AssertionError("LLM must not run for a no-input session recap")

        async def arun(self, prompt):
            return self.run(prompt)

    view = run_recap_turn(
        FakeReporter(),
        profile_dir=tmp_path,
        session_id=sid,
        coach_agent=Boom(),
        formatter_agent=Boom(),
    )
    assert view["status"] == "ended"
    assert view["recap"]
    assert view["turns"][-1]["kind"] == "recap"


def test_discard_recap_and_late_approval(tmp_path):
    profile_dir, sid = _drafted_session(tmp_path)
    view = run_recap_turn(
        FakeReporter(),
        profile_dir=profile_dir,
        session_id=sid,
        coach_agent=FakeAgent("notes"),
        formatter_agent=FakeAgent(
            CoachTurn(message="Covered Acme; K8s remains open.", action="recap", topic_id="t1")
        ),
    )
    assert view["status"] == "ended"
    assert approve_draft(
        profile_dir,
        sid,
        "t1",
        title="Acme deploys",
        summary="Cut deploy time from 40 min to 6 min.",
        quotes=["I cut deploy time from 40 min to 6 min."],
    )

    other_profile = tmp_path / "other"
    _seed_primary(other_profile)
    other_sid = _open(other_profile)["sessionId"]
    run_message_turn(
        FakeReporter(),
        profile_dir=other_profile,
        session_id=other_sid,
        message="Shipped the tool.",
        coach_agent=FakeAgent("notes"),
        formatter_agent=FakeAgent(
            CoachTurn(
                message="Draft.",
                action="draft",
                topic_id="t1",
                draft_note=DraftNote(title="Tool", summary="Shipped the tool.", quotes=["Shipped the tool."]),
            )
        ),
    )
    discard_draft(other_profile, other_sid, "t1")
    assert session_view(other_profile, other_sid)["draftNotes"][0]["status"] == "discarded"


def test_build_with_impact_records_errors(tmp_path, monkeypatch):
    profile_dir, sid = _drafted_session(tmp_path)
    import resume_agent.services.profile_coach as service

    monkeypatch.setattr(service, "run_corpus_build", lambda reporter, **kwargs: {"experiences": 1})
    report = run_build_with_impact(
        FakeReporter(),
        profile_dir=profile_dir,
        session_id=sid,
        facts_out=profile_dir / "facts.json",
        github_username=None,
    )
    assert report["impact"] == session_view(profile_dir, sid)["impact"]

    monkeypatch.setattr(
        service,
        "run_corpus_build",
        lambda reporter, **kwargs: (_ for _ in ()).throw(RuntimeError("build exploded")),
    )
    with pytest.raises(RuntimeError):
        run_build_with_impact(
            FakeReporter(),
            profile_dir=profile_dir,
            session_id=sid,
            facts_out=profile_dir / "facts.json",
            github_username=None,
        )
    assert session_view(profile_dir, sid)["impact"] == {"error": "build exploded"}
