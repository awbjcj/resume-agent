from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from resume_tailor_harness.profile.coach import CoachTurn, DraftNote, NewTopic, OpeningTurn
from resume_tailor_harness.profile.coach_store import load_session, mutate_session
from resume_tailor_harness.services.profile_coach import (
    approve_draft,
    discard_draft,
    run_build_with_impact,
    run_message_turn,
    run_opening_turn,
    run_recap_turn,
    session_view,
    sessions_view,
)
from resume_tailor_harness.sessions.stream import (
    Completed,
    Failed,
    Notice,
    StreamEvent,
    TextDelta,
    ToolStarted,
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


class RecordingSink:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)

    def close(self):
        pass

    @property
    def text(self):
        return "".join(
            event.text for event in self.events if isinstance(event, TextDelta)
        )


class StreamingAgent:
    def __init__(self, prose: str, metadata: str = "action: ask\ntopic: t1"):
        self.full = f"{prose}\n---METADATA---\n{metadata}"
        self.prompts: list[str] = []

    def stream(self, prompt) -> Iterator[StreamEvent]:
        self.prompts.append(prompt)
        split = max(1, len(self.full) // 2)
        yield TextDelta(self.full[:split])
        yield ToolStarted("call-1", "search_corpus", "Kafka")
        yield TextDelta(self.full[split:])
        yield Completed(SimpleNamespace(content=self.full))

    def run(self, prompt):
        return SimpleNamespace(content=self.full)

    async def arun(self, prompt):
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
    from resume_tailor_harness.profile.corpus import add_source

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


def test_opening_turn_seeds_measured_depth_topics_before_model_topics(tmp_path):
    from resume_tailor_harness.models.profile import Bullet, Contact, Experience, ProfileFacts
    from resume_tailor_harness.profile.store import save_facts

    _seed_primary(tmp_path)
    save_facts(
        ProfileFacts(
            contact=Contact(name="Ada"),
            experience=[
                Experience(
                    id="exp-acme",
                    company="Acme",
                    title="Engineer",
                    bullets=[Bullet(id="b1", text="Built it")],
                )
            ],
        ),
        tmp_path / "facts.json",
    )
    coach = FakeAgent("notes")
    view = run_opening_turn(
        FakeReporter(),
        profile_dir=tmp_path,
        coach_agent=coach,
        formatter_agent=FakeAgent(
            OpeningTurn(message="What changed at Acme?", action="ask", topics=[])
        ),
    )

    assert view["topics"][0]["ownerId"] == "exp-acme"
    assert "SEEDED DEPTH AGENDA" in coach.prompts[0]


def test_session_view_exposes_owner_id_in_camel_case(tmp_path):
    from resume_tailor_harness.profile.coach_store import (
        CoachTopic,
        CoachTurnRecord,
        create_session,
    )

    create_session(
        tmp_path,
        "owner",
        [CoachTopic(id="t1", gap="Acme", owner_id="exp-acme")],
        CoachTurnRecord(role="coach", kind="question", text="First?", topic_id="t1"),
    )

    assert session_view(tmp_path, "owner")["topics"][0]["ownerId"] == "exp-acme"


def test_message_streams_prose_and_stores_the_same_text(tmp_path):
    sid = _open(tmp_path)["sessionId"]
    sink = RecordingSink()
    coach = StreamingAgent("Strong answer.")

    run_message_turn(
        FakeReporter(),
        profile_dir=tmp_path,
        session_id=sid,
        message="I improved deploys.",
        coach_agent=coach,
        formatter_agent=FakeAgent(
            CoachTurn(message="Formatter drift.", action="ask", topic_id="t1")
        ),
        sink=sink,
    )

    assert sink.text == "Strong answer."
    assert session_view(tmp_path, sid)["turns"][-1]["text"] == sink.text
    assert any(isinstance(event, ToolStarted) for event in sink.events)
    assert not any(isinstance(event, Completed) for event in sink.events)
    assert coach.prompts[0].index("TRANSCRIPT:") < coach.prompts[0].index("AGENDA:")


def test_session_view_hides_metadata_from_an_existing_coach_turn(tmp_path):
    sid = _open(tmp_path)["sessionId"]

    def contaminate(session):
        session["turns"][0]["text"] = (
            "What changed after launch?\nMETADATA---\\\naction: ask\ntopic_id: t1"
        )

    mutate_session(tmp_path, sid, contaminate)

    assert session_view(tmp_path, sid)["turns"][0]["text"] == (
        "What changed after launch?"
    )
    assert "action: ask" in load_session(tmp_path, sid)["turns"][0]["text"]


def test_partial_stream_failure_leaves_session_byte_equivalent(tmp_path):
    sid = _open(tmp_path)["sessionId"]
    before = load_session(tmp_path, sid)

    class BrokenStream(StreamingAgent):
        def stream(self, prompt) -> Iterator[StreamEvent]:
            yield TextDelta("Partial answer")
            yield Failed("provider lost", "PROVIDER_ERROR")

    with pytest.raises(RuntimeError, match="provider lost"):
        run_message_turn(
            FakeReporter(),
            profile_dir=tmp_path,
            session_id=sid,
            message="I improved deploys.",
            coach_agent=BrokenStream("unused"),
            formatter_agent=FakeAgent(
                CoachTurn(message="must not persist", action="ask", topic_id="t1")
            ),
            sink=RecordingSink(),
        )

    assert load_session(tmp_path, sid) == before


def test_missing_delimiter_degrades_instead_of_losing_the_turn(tmp_path):
    # DeepSeek v4 never emits the sentinel -- verified against the live coach
    # prompt with thinking on and off, while Claude honours it -- and the run
    # completes normally, so there is nothing to retry. Failing here threw away
    # a perfectly good answer the formatter can still structure, so the whole
    # response becomes both the visible reply and the formatter's notes.
    sid = _open(tmp_path)["sessionId"]
    reply = "Strong answer with no delimiter at all."

    class NoDelimiterStream(StreamingAgent):
        def __init__(self):
            self.full = reply
            self.prompts = []

    formatter = FakeAgent(CoachTurn(message="formatted", action="ask", topic_id="t1"))
    view = run_message_turn(
        FakeReporter(),
        profile_dir=tmp_path,
        session_id=sid,
        message="I improved deploys.",
        coach_agent=NoDelimiterStream(),
        formatter_agent=formatter,
        sink=RecordingSink(),
    )

    # The undelimited response reaches the formatter as notes...
    assert reply in formatter.prompts[0]
    # ...and the prose the user already watched stream is what gets stored,
    # not the formatter's paraphrase.
    assert view["turns"][-1]["text"] == reply


def test_stream_checks_cancellation_before_each_visible_event(tmp_path):
    sid = _open(tmp_path)["sessionId"]
    before = load_session(tmp_path, sid)

    class Cancelled(RuntimeError):
        pass

    class CancellingReporter(FakeReporter):
        checks = 0

        def checkpoint(self):
            self.checks += 1
            if self.checks == 2:
                raise Cancelled("stop")

    sink = RecordingSink()
    with pytest.raises(Cancelled):
        run_message_turn(
            CancellingReporter(),
            profile_dir=tmp_path,
            session_id=sid,
            message="I improved deploys.",
            coach_agent=StreamingAgent("Strong answer."),
            formatter_agent=FakeAgent(
                CoachTurn(message="ignored", action="ask", topic_id="t1")
            ),
            sink=sink,
        )

    assert load_session(tmp_path, sid) == before
    assert not any(isinstance(event, ToolStarted) for event in sink.events)


def test_stream_disabled_uses_blocking_formatter_message(tmp_path, monkeypatch):
    sid = _open(tmp_path)["sessionId"]
    monkeypatch.setattr(
        "resume_tailor_harness.sessions.turns.get_settings",
        lambda: SimpleNamespace(stream_enabled=False),
    )
    sink = RecordingSink()

    run_message_turn(
        FakeReporter(),
        profile_dir=tmp_path,
        session_id=sid,
        message="I improved deploys.",
        coach_agent=StreamingAgent("Streamed text."),
        formatter_agent=FakeAgent(
            CoachTurn(message="Blocking text.", action="ask", topic_id="t1")
        ),
        sink=sink,
    )

    assert sink.events == []
    assert session_view(tmp_path, sid)["turns"][-1]["text"] == "Blocking text."


def test_bad_draft_notice_is_durable_and_emitted_before_terminal(tmp_path):
    sid = _open(tmp_path)["sessionId"]
    bad = CoachTurn(
        message="Drafted.",
        action="draft",
        topic_id="t1",
        draft_note=DraftNote(title="T", summary="S", quotes=["never said"]),
    )
    sink = RecordingSink()

    run_message_turn(
        FakeReporter(),
        profile_dir=tmp_path,
        session_id=sid,
        message="I led it.",
        coach_agent=StreamingAgent("Drafted."),
        formatter_agent=FakeAgent(bad, bad),
        sink=sink,
    )

    turn = session_view(tmp_path, sid)["turns"][-1]
    assert "quote check" in turn["notice"].lower()
    assert session_view(tmp_path, sid)["draftNotes"] == []
    assert any(isinstance(event, Notice) for event in sink.events)


def test_streamed_prose_survives_structural_formatter_failure(tmp_path):
    sid = _open(tmp_path)["sessionId"]
    bad = CoachTurn(message="", action="ask", topic_id="missing")
    sink = RecordingSink()

    view = run_message_turn(
        FakeReporter(),
        profile_dir=tmp_path,
        session_id=sid,
        message="I improved deploys.",
        coach_agent=StreamingAgent("Could you quantify that?"),
        formatter_agent=FakeAgent(bad, bad),
        sink=sink,
    )

    assert view["turns"][-1]["text"] == "Could you quantify that?"
    assert "details could not be read" in view["turns"][-1]["notice"]
    assert any(isinstance(event, Notice) for event in sink.events)


def test_streamed_prose_survives_unparsable_formatter_output(tmp_path, caplog):
    sid = _open(tmp_path)["sessionId"]

    view = run_message_turn(
        FakeReporter(),
        profile_dir=tmp_path,
        session_id=sid,
        message="I improved deploys.",
        coach_agent=StreamingAgent("Could you quantify that?"),
        formatter_agent=FakeAgent("not structured output"),
    )

    assert view["turns"][-1]["text"] == "Could you quantify that?"
    assert "details could not be read" in view["turns"][-1]["notice"]
    assert "Coach formatter returned unusable output" in caplog.text


def test_blocking_formatter_message_survives_structural_failure(tmp_path):
    sid = _open(tmp_path)["sessionId"]
    bad = CoachTurn(
        message="Could you quantify that?", action="ask", topic_id="missing"
    )

    view = run_message_turn(
        FakeReporter(),
        profile_dir=tmp_path,
        session_id=sid,
        message="I improved deploys.",
        coach_agent=FakeAgent("notes"),
        formatter_agent=FakeAgent(bad, bad),
    )

    assert view["turns"][-1]["text"] == "Could you quantify that?"
    assert view["turns"][-1]["notice"]


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
    from resume_tailor_harness.profile.corpus import load_manifest

    assert len(load_manifest(profile_dir).docs) == 2


def test_approving_a_seeded_topic_writes_a_pinned_synthesis_note(tmp_path):
    from resume_tailor_harness.profile.coach_store import (
        CoachDraftNote,
        CoachTopic,
        CoachTurnRecord,
        apply_turn_delta,
        create_session,
    )
    from resume_tailor_harness.profile.corpus import load_manifest

    profile_dir = tmp_path / "profile"
    _seed_primary(profile_dir)
    create_session(
        profile_dir,
        "seeded",
        [CoachTopic(id="t1", gap="Acme", owner_id="exp-acme")],
        CoachTurnRecord(role="coach", kind="question", text="First?", topic_id="t1"),
    )
    apply_turn_delta(
        profile_dir,
        "seeded",
        user_text="I cut deploy time from 40 minutes to 6 minutes.",
        coach_turn=CoachTurnRecord(
            role="coach", kind="draft_note", text="Draft", topic_id="t1"
        ),
        new_topics=[],
        skipped_topic_ids=[],
        draft=CoachDraftNote(
            topic_id="t1",
            title="Deploy speed",
            summary="Cut deploy time.",
            quotes=["I cut deploy time from 40 minutes to 6 minutes."],
        ),
    )

    doc_id = approve_draft(
        profile_dir,
        "seeded",
        "t1",
        title="Deploy speed",
        summary="Cut deploy time.",
        quotes=["I cut deploy time from 40 minutes to 6 minutes."],
    )

    doc = next(doc for doc in load_manifest(profile_dir).docs if doc.id == doc_id)
    assert (doc.mode, doc.anchor) == ("synthesis", "exp-acme")


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
            CoachTurn(
                message="Covered Acme; K8s remains open.", action="recap", topic_id="t1"
            )
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
                draft_note=DraftNote(
                    title="Tool",
                    summary="Shipped the tool.",
                    quotes=["Shipped the tool."],
                ),
            )
        ),
    )
    discard_draft(other_profile, other_sid, "t1")
    assert (
        session_view(other_profile, other_sid)["draftNotes"][0]["status"] == "discarded"
    )


def test_build_with_impact_records_errors(tmp_path, monkeypatch):
    profile_dir, sid = _drafted_session(tmp_path)
    import resume_tailor_harness.services.profile_coach as service

    monkeypatch.setattr(
        service, "run_corpus_build", lambda reporter, **kwargs: {"experiences": 1}
    )
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
        lambda reporter, **kwargs: (_ for _ in ()).throw(
            RuntimeError("build exploded")
        ),
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
