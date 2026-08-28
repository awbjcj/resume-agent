"""persona_output: streaming prose/metadata split and its degradation rules.

The persona stack asks a model to write prose, then a ``---METADATA---``
sentinel, then formatter input. Compliance is a model behaviour, not an
invariant we control: DeepSeek v4 ignores the sentinel outright (verified
against the live coach prompt on both thinking and non-thinking modes) while
Claude honours it. These tests pin what happens on each side of that.
"""

from types import SimpleNamespace

import pytest

from resume_agent.sessions.stream import Completed, Failed, Settled, TextDelta
from resume_agent.sessions.turns import DELIMITER, StreamFailed, persona_output


class _Sink:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)

    def close(self):
        return None

    @property
    def text(self):
        return "".join(e.text for e in self.events if isinstance(e, TextDelta))


class _Reporter:
    def __init__(self):
        self.checkpoints = 0

    def checkpoint(self):
        self.checkpoints += 1


class _Agent:
    """An agent whose stream replays a scripted event sequence."""

    def __init__(self, events, run_content="from run()"):
        self._events = list(events)
        self._run_content = run_content
        self.run_calls = 0

    def stream(self, prompt):
        yield from self._events

    def run(self, prompt):
        self.run_calls += 1

        class _Resp:
            content = self._run_content

        return _Resp()


def _deltas(*chunks):
    return [TextDelta(chunk) for chunk in chunks]


def test_missing_delimiter_degrades_to_the_whole_output_instead_of_failing():
    # DeepSeek v4-pro completes normally (status COMPLETED, no truncation) and
    # never emits the sentinel. The formatter is an LLM that extracts the turn
    # from raw notes regardless, so losing the turn costs the user their whole
    # answer to buy nothing.
    sink, reporter = _Sink(), _Reporter()
    agent = _Agent(
        [*_deltas("Good context. ", "What did it move?"), Completed(object())]
    )

    prose, full = persona_output(agent, "p", sink, reporter, source="coach notes")

    assert prose == "Good context. What did it move?"
    assert full == prose
    assert sink.text == prose


def test_delimiter_present_still_hides_metadata_from_the_user():
    sink, reporter = _Sink(), _Reporter()
    agent = _Agent(
        [*_deltas("Nice work.\n", DELIMITER, "\naction: ask"), Completed(object())]
    )

    prose, full = persona_output(agent, "p", sink, reporter, source="coach notes")

    assert prose == "Nice work."
    assert sink.text == "Nice work."
    assert "action: ask" in full
    assert isinstance(sink.events[-1], Settled)


def test_marker_wrapped_in_markdown_emphasis_is_still_the_marker():
    # Models routinely bold or pad a literal sentinel. Treating that as prose
    # dumps the formatter payload into the chat window.
    sink, reporter = _Sink(), _Reporter()
    agent = _Agent(
        [
            *_deltas("Nice work.\n", "**--- METADATA ---**", "\naction: ask"),
            Completed(object()),
        ]
    )

    prose, _ = persona_output(agent, "p", sink, reporter, source="coach notes")

    assert prose == "Nice work."
    assert "action" not in sink.text


def test_marker_missing_its_leading_rule_is_hidden_across_stream_deltas():
    # DeepSeek can emit the requested token as `METADATA---\` instead of the
    # exact sentinel. Stream it one character at a time to prove that no prefix
    # of the malformed marker is flushed before the boundary is complete.
    sink, reporter = _Sink(), _Reporter()
    body = "Clear question.\nMETADATA---\\\naction: ask\ntopic_id: t1"
    agent = _Agent([*_deltas(*body), Completed(object())])

    prose, full = persona_output(agent, "p", sink, reporter, source="coach notes")

    assert prose == "Clear question."
    assert sink.text == prose
    assert "topic_id: t1" in full


def test_metadata_block_without_a_sentinel_is_still_hidden_from_the_user():
    # The degradation rule (missing sentinel -> show everything) is only safe
    # when there is nothing to hide. A model that emits the block but forgets
    # the sentinel would otherwise dump `action:`/`topic_updates:`/`draft:`
    # straight into the chat. The block announces itself with the schema's own
    # keys, so that is the boundary when the sentinel is absent.
    sink, reporter = _Sink(), _Reporter()
    chunks = [
        "Which project moved a number?\n",
        "\naction: ask_question\n",
        "topic_id: aptiv_triage\n",
        "topic_updates:\n  - id: aptiv_triage\n    status: active\n",
        "research_actions: []",
    ]
    agent = _Agent([*_deltas(*chunks), Completed(object())])

    prose, full = persona_output(agent, "p", sink, reporter, source="coach notes")

    assert prose == "Which project moved a number?"
    assert sink.text == prose
    # The formatter still receives the block verbatim -- this hides it, it does
    # not discard it.
    assert "topic_id: aptiv_triage" in full
    assert "research_actions" in full


def test_prose_mentioning_a_schema_word_inline_is_not_truncated():
    # The cut requires a bare key alone at the start of a line after a blank
    # one. Coaches write "**Action:** ..." and "the draft: ..." mid-sentence,
    # and truncating a reply there would be far worse than the leak it guards.
    sink, reporter = _Sink(), _Reporter()
    body = (
        "Here is the plan: quantify the triage work.\n\n"
        "**Action:** name the baseline. Your draft: still needs a metric.\n\n"
        "What was the before number?"
    )
    agent = _Agent([*_deltas(body), Completed(object())])

    prose, _ = persona_output(agent, "p", sink, reporter, source="coach notes")

    assert prose == body


def test_bare_horizontal_rule_is_never_mistaken_for_the_marker():
    # DeepSeek's real coach output uses `---` as a section break between the
    # agenda and the question. Matching the rules alone would truncate the
    # reply mid-turn.
    sink, reporter = _Sink(), _Reporter()
    body = "Here is the agenda.\n\n---\n\nWhich project moved a number?"
    agent = _Agent([*_deltas(body), Completed(object())])

    prose, _ = persona_output(agent, "p", sink, reporter, source="coach notes")

    assert prose == body


def test_plain_metadata_heading_is_not_mistaken_for_the_marker():
    sink, reporter = _Sink(), _Reporter()
    body = "Metadata\n\nWhich field should we verify?"
    agent = _Agent([*_deltas(body), Completed(object())])

    prose, _ = persona_output(agent, "p", sink, reporter, source="coach notes")

    assert prose == body


def test_a_failed_stream_still_raises_rather_than_degrading():
    sink, reporter = _Sink(), _Reporter()
    agent = _Agent([TextDelta("partial"), Failed("upstream 503", "PROVIDER_ERROR")])

    with pytest.raises(StreamFailed) as excinfo:
        persona_output(agent, "p", sink, reporter, source="coach notes")

    assert excinfo.value.code == "PROVIDER_ERROR"


def test_a_stream_with_no_terminal_event_still_raises():
    sink, reporter = _Sink(), _Reporter()
    agent = _Agent(_deltas("orphaned"))

    with pytest.raises(StreamFailed) as excinfo:
        persona_output(agent, "p", sink, reporter, source="coach notes")

    assert excinfo.value.code == "STREAM_ERROR"


def test_a_silent_stream_falls_back_to_the_terminal_response():
    sink, reporter = _Sink(), _Reporter()
    agent = _Agent([Completed(SimpleNamespace(content="from the run output"))])

    prose, full = persona_output(agent, "p", sink, reporter, source="coach notes")

    assert prose == ""
    assert full == "from the run output"
    assert not any(isinstance(event, Settled) for event in sink.events)
