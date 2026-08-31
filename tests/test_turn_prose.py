from resume_tailor_harness.sessions.stream import TextDelta
from resume_tailor_harness.sessions.turns import DELIMITER, ProseEmitter


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


def test_finish_is_idempotent():
    sink = _Recorder()
    emitter = ProseEmitter(sink)
    emitter.feed("short")
    assert sink.text == "short"

    first = emitter.finish()
    second = emitter.finish()

    assert first == second == ("short", "short")
    assert sink.text == "short"


def test_boundary_free_prose_flushes_without_a_fixed_holdback():
    sink = _Recorder()
    emitter = ProseEmitter(sink)
    body = "a complete boundary-free sentence"

    emitter.feed(body)

    assert sink.text == body
    emitter.finish()
    assert sink.text == body


def test_blank_line_candidate_is_withheld_until_disambiguated():
    sink = _Recorder()
    emitter = ProseEmitter(sink)
    emitter.feed("Visible prose.\n\n--")
    assert sink.text == "Visible prose."
    emitter.feed("ordinary continuation")
    assert sink.text == "Visible prose.\n\n--ordinary continuation"


def test_boundary_split_across_three_deltas_never_leaks():
    sink = _Recorder()
    emitter = ProseEmitter(sink)
    for chunk in ["Visible prose.\n\n", "PRO", "POSE | company | ats"]:
        emitter.feed(chunk)
    prose, _ = emitter.finish()
    assert prose == "Visible prose."
    assert "PRO" not in sink.text


def test_full_output_preserves_delimiter_and_metadata_for_formatter():
    sink = _Recorder()
    emitter = ProseEmitter(sink)
    emitter.feed("Prose.\n" + DELIMITER + '\naction: draft\nquote: "we cut p99"')

    _, full = emitter.finish()

    assert DELIMITER in full
    assert "we cut p99" in full


def test_answer_hints_are_a_boundary_without_the_sentinel():
    sink = _Recorder()
    emitter = ProseEmitter(sink)

    emitter.feed(
        "Tell me about a difficult trade-off.\n\n"
        "hints:\n- Set the context.\n- Explain the alternatives."
    )
    prose, full = emitter.finish()

    assert prose == "Tell me about a difficult trade-off."
    assert "Set the context" not in sink.text
    assert "hints:" in full


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

    emitter.feed(
        "I would PROPOSE | as a separator, and AVOID | commas.\nStill talking."
    )
    prose, _full = emitter.finish()

    assert (
        prose == "I would PROPOSE | as a separator, and AVOID | commas.\nStill talking."
    )
