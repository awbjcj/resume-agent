from resume_agent.sessions.stream import TextDelta
from resume_agent.sessions.turns import DELIMITER, ProseEmitter


class _Recorder:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)

    def close(self):
        return None

    @property
    def text(self):
        return "".join(
            event.text for event in self.events if isinstance(event, TextDelta)
        )


def test_prose_before_delimiter_is_emitted_and_matches_stored_text():
    sink = _Recorder()
    emitter = ProseEmitter(sink)

    emitter.feed("Hello there.\n" + DELIMITER + "\naction: ask")
    prose, full = emitter.finish()

    assert prose == "Hello there."
    assert sink.text == prose
    assert "action: ask" in full


def test_delimiter_split_across_chunks_never_leaks_a_partial():
    sink = _Recorder()
    emitter = ProseEmitter(sink)
    for chunk in ["Good answer.\n", "---METAD", "ATA---\n", "action: draft"]:
        emitter.feed(chunk)

    prose, _ = emitter.finish()

    assert prose == "Good answer."
    assert sink.text == prose
    assert "METAD" not in sink.text


def test_missing_delimiter_treats_everything_as_verbatim_prose():
    sink = _Recorder()
    emitter = ProseEmitter(sink)

    emitter.feed("  A message with intentional space.  ")
    prose, full = emitter.finish()

    assert prose == "  A message with intentional space.  "
    assert full == prose
    assert sink.text == prose


def test_holdback_flushes_on_finish_and_finish_is_idempotent():
    sink = _Recorder()
    emitter = ProseEmitter(sink, holdback=32)
    emitter.feed("short")
    assert sink.text == ""

    first = emitter.finish()
    second = emitter.finish()

    assert first == second == ("short", "short")
    assert sink.text == "short"


def test_long_prose_streams_before_finish():
    sink = _Recorder()
    emitter = ProseEmitter(sink, holdback=8)

    emitter.feed("abcdefghijklmnopqrstuvwx")

    assert sink.text == "abcdefgh"
    emitter.finish()
    assert sink.text == "abcdefghijklmnopqrstuvwx"


def test_full_output_preserves_delimiter_and_metadata_for_formatter():
    sink = _Recorder()
    emitter = ProseEmitter(sink)
    emitter.feed('Prose.\n' + DELIMITER + '\naction: draft\nquote: "we cut p99"')

    _, full = emitter.finish()

    assert DELIMITER in full
    assert "we cut p99" in full
