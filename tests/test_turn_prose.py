from resume_agent.sessions.stream import TextDelta
from resume_agent.sessions.turns import DELIMITER, MARKER_MAX_LEN, ProseEmitter


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
    # The holdback floor is whatever the longest possible marker needs, so a
    # marker arriving one delta at a time can never be flushed as prose. A
    # caller asking for less gets the floor, not their number.
    sink = _Recorder()
    emitter = ProseEmitter(sink, holdback=8)
    floor = MARKER_MAX_LEN + 2
    body = "x" * (floor + 10)

    emitter.feed(body)

    assert sink.text == "x" * 10
    emitter.finish()
    assert sink.text == body


def test_full_output_preserves_delimiter_and_metadata_for_formatter():
    sink = _Recorder()
    emitter = ProseEmitter(sink)
    emitter.feed('Prose.\n' + DELIMITER + '\naction: draft\nquote: "we cut p99"')

    _, full = emitter.finish()

    assert DELIMITER in full
    assert "we cut p99" in full


def test_scout_metadata_rows_are_a_boundary_without_the_sentinel():
    # The Scout's metadata block is a `PROPOSE | ... | ...` table, not the
    # `key: value` lines the block guard was written for, so a model that omits
    # the sentinel -- DeepSeek does, on every turn -- dumped the whole proposal
    # table into the chat window.
    sink = _Recorder()
    emitter = ProseEmitter(sink)

    emitter.feed(
        "I found two leads.\n\n"
        "PROPOSE | Anduril | greenhouse | https://boards.example/anduril | fit\n"
        "AVOID | Glean | ashby | https://jobs.example/glean | 404\n"
    )
    prose, full = emitter.finish()

    assert prose == "I found two leads."
    assert "PROPOSE" not in sink.text
    assert "PROPOSE | Anduril" in full


def test_pipe_prose_is_not_mistaken_for_a_metadata_row():
    sink = _Recorder()
    emitter = ProseEmitter(sink)

    emitter.feed("I would PROPOSE | as a separator, and AVOID | commas.\nStill talking.")
    prose, _full = emitter.finish()

    assert prose == "I would PROPOSE | as a separator, and AVOID | commas.\nStill talking."
