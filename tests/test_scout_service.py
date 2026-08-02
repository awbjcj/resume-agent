from dataclasses import dataclass
from typing import Literal, cast

import pytest

from resume_agent.api.schemas.config import SearchConfigDoc
from resume_agent.discovery.scout import ScoutTurnDraft
from resume_agent.discovery.scout_store import (
    ScoutProposal,
    ScoutTurnRecord,
    SourcePayload,
    TermPayload,
    create_session_from_turn,
    end_session,
    load_session,
)
from resume_agent.services import scout as service
from resume_agent.services.config_store import YamlConfigStore
from resume_agent.services.sources import SourcePreview
from resume_agent.sessions.stream import (
    Completed,
    TextDelta,
    ToolCompleted,
    ToolStarted,
)


class Reporter:
    def begin(self, total, label, **kwargs):
        pass

    def step(self, current, **kwargs):
        pass

    def checkpoint(self):
        pass


@dataclass
class Result:
    content: object


class Formatter:
    def __init__(self, turn: ScoutTurnDraft):
        self.turn = turn

    def run(self, prompt: str) -> Result:
        return Result(self.turn)

    async def arun(self, prompt: str) -> Result:
        return self.run(prompt)


class StreamingScout:
    def __init__(self, text="Found one option."):
        self.text = text
        self.prompts = []

    def stream(self, prompt):
        self.prompts.append(prompt)
        yield TextDelta(self.text)
        yield ToolStarted("t1", "web_search", "AI infrastructure")
        yield ToolCompleted("t1", "web_search", "results")
        yield Completed(Result(self.text))

    def run(self, prompt):
        self.prompts.append(prompt)
        return Result(self.text)

    async def arun(self, prompt):
        return self.run(prompt)


CheckStatus = Literal["validated", "unverified", "failed", "duplicate", "avoid", "new"]


def source_proposal(company: str = "Modal", check: CheckStatus = "validated") -> ScoutProposal:
    return ScoutProposal(
        kind="source",
        source=SourcePayload(company=company, url=f"https://{company.casefold()}.example/jobs"),
        check=check,
    )


def term_proposal(value="inference serving"):
    return ScoutProposal(kind="search_term", term=TermPayload(value=value), check="new")


def test_streamed_prose_is_stored_and_source_is_authoritatively_probed(monkeypatch, tmp_path):
    monkeypatch.setattr(
        service,
        "preview_source",
        lambda url, **kwargs: SourcePreview(
            ok=True, url="https://jobs.lever.co/modal", kind="lever", token="modal", role_count=4
        ),
    )
    sink = _Sink()
    view = service.run_start_turn(
        Reporter(),
        workspace_root=tmp_path,
        session_id="s1",
        message="AI infra",
        connectors_path=str(tmp_path / "config" / "connectors.yaml"),
        search_path=str(tmp_path / "config" / "search.yaml"),
        profile_dir=tmp_path / "profile",
        browser_enabled=False,
        sink=sink,
        scout_agent=StreamingScout(),
        formatter_agent=Formatter(
            ScoutTurnDraft.model_validate(
                {
                    "message": "Formatter wording",
                    "proposals": [
                        {
                            "kind": "source",
                            "source": {"company": "Modal", "url": "https://modal.example/jobs"},
                        }
                    ],
                }
            )
        ),
    )
    assert view["turns"][-1]["text"] == "Found one option."
    assert view["proposals"][0]["check"] == "validated"
    assert view["proposals"][0]["source"]["url"] == "https://jobs.lever.co/modal"
    assert view["proposals"][0]["source"]["roleCount"] == 4
    assert "".join(event.text for event in sink.events if isinstance(event, TextDelta)) == "Found one option."
    assert [
        type(event).__name__
        for event in sink.events
        if isinstance(event, (ToolStarted, ToolCompleted))
    ] == ["ToolStarted", "ToolCompleted"]


class _Sink:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)

    def close(self):
        pass


def test_dismissed_feedback_is_in_next_prompt(tmp_path):
    create_session_from_turn(
        tmp_path,
        "s1",
        goal="AI infra",
        user_text="AI infra",
        scout_turn=ScoutTurnRecord(role="scout", text="First"),
        proposals=[source_proposal("Scale-AI")],
    )
    service.dismiss_proposal(tmp_path, "s1", "p1", reason="too big", browser_enabled=False)
    runner = StreamingScout("Here are smaller teams.")
    service.run_message_turn(
        Reporter(),
        workspace_root=tmp_path,
        session_id="s1",
        message="find smaller ones",
        connectors_path=str(tmp_path / "config" / "connectors.yaml"),
        search_path=str(tmp_path / "config" / "search.yaml"),
        profile_dir=tmp_path / "profile",
        browser_enabled=False,
        scout_agent=runner,
        formatter_agent=Formatter(ScoutTurnDraft(message="Here are smaller teams.")),
    )
    assert "DISMISSED — DO NOT PROPOSE AGAIN" in runner.prompts[0]
    assert "Scale-AI — user said: too big" in runner.prompts[0]


def test_repeated_source_and_term_are_stored_as_duplicates(tmp_path):
    create_session_from_turn(
        tmp_path,
        "s1",
        goal="AI infra",
        user_text="AI infra",
        scout_turn=ScoutTurnRecord(role="scout", text="First"),
        proposals=[source_proposal(), term_proposal()],
    )
    turn = ScoutTurnDraft.model_validate(
        {
            "message": "Repeated",
            "proposals": [
                {"kind": "source", "source": {"company": "Modal", "url": "https://other.example/jobs"}},
                {"kind": "search_term", "term": {"value": "Inference Serving"}},
            ],
        }
    )
    view = service.run_message_turn(
        Reporter(),
        workspace_root=tmp_path,
        session_id="s1",
        message="more",
        connectors_path=str(tmp_path / "connectors.yaml"),
        search_path=str(tmp_path / "search.yaml"),
        profile_dir=tmp_path,
        browser_enabled=False,
        scout_agent=StreamingScout("Repeated"),
        formatter_agent=Formatter(turn),
    )
    assert [row["check"] for row in view["proposals"][-2:]] == ["duplicate", "duplicate"]


def test_term_approval_preserves_unrelated_fields(tmp_path):
    create_session_from_turn(
        tmp_path,
        "s1",
        goal="AI infra",
        user_text="AI infra",
        scout_turn=ScoutTurnRecord(role="scout", text="First"),
        proposals=[term_proposal()],
    )
    store = YamlConfigStore(tmp_path / "config")
    store.put("search", SearchConfigDoc(keywords=["python"], min_salary=180_000))
    view = service.approve_proposal(
        tmp_path,
        "s1",
        "p1",
        config_store=store,
        connectors_path=str(tmp_path / "config" / "connectors.yaml"),
        search_path=str(tmp_path / "config" / "search.yaml"),
        browser_enabled=False,
    )
    saved = cast(SearchConfigDoc, store.get("search"))
    assert saved.keywords == ["python", "inference serving"]
    assert saved.min_salary == 180_000
    assert view["proposals"][0]["status"] == "added"


def test_server_rejects_non_approvable_source_and_allows_resolution_after_end(tmp_path):
    create_session_from_turn(
        tmp_path,
        "s1",
        goal="AI infra",
        user_text="AI infra",
        scout_turn=ScoutTurnRecord(role="scout", text="First"),
        proposals=[source_proposal(check="failed")],
    )
    end_session(tmp_path, "s1", "Done")
    with pytest.raises(ValueError, match="not approvable"):
        service.approve_proposal(
            tmp_path,
            "s1",
            "p1",
            config_store=YamlConfigStore(tmp_path / "config"),
            connectors_path=str(tmp_path / "connectors.yaml"),
            search_path=str(tmp_path / "search.yaml"),
            browser_enabled=False,
        )
    dismissed = service.dismiss_proposal(
        tmp_path, "s1", "p1", reason="broken", browser_enabled=False
    )
    assert dismissed["proposals"][0]["status"] == "dismissed"
    assert load_session(tmp_path, "s1")["status"] == "ended"


class UnparsableFormatter:
    """A formatter whose provider returned prose instead of the schema."""

    def run(self, prompt: str) -> Result:
        return Result("Sure! Here is the JSON you asked for:")

    async def arun(self, prompt: str) -> Result:
        return self.run(prompt)


def test_unparsable_formatter_keeps_the_reply_the_user_already_watched(tmp_path, caplog):
    # agno reports "could not coerce into output_schema" by handing back a raw
    # str, which expect_schema raises as UnparsedAgentOutput -- a TypeError, so
    # the TurnRejected fallback never saw it. The researcher's answer has
    # already streamed into the chat by then, so failing the run deletes a reply
    # the user just read. Degrade like every other formatter failure, but log
    # the diagnostic so the provider fault stays visible.
    view = service.run_start_turn(
        Reporter(),
        workspace_root=tmp_path,
        session_id="s1",
        message="AI infra",
        connectors_path=str(tmp_path / "connectors.yaml"),
        search_path=str(tmp_path / "search.yaml"),
        profile_dir=tmp_path,
        browser_enabled=False,
        scout_agent=StreamingScout("Found one option."),
        formatter_agent=UnparsableFormatter(),
    )
    assert view["turns"][-1]["text"] == "Found one option."
    assert view["turns"][-1]["notice"] == service._TURN_OMITTED_NOTICE
    assert view["proposals"] == []
    assert any("Expected ScoutTurnDraft" in record.getMessage() for record in caplog.records)
