import json

from resume_agent.sessions.stream import (
    Completed,
    ConsoleStreamSink,
    Failed,
    Notice,
    NullSink,
    ReasoningDelta,
    RunStreamSink,
    TextDelta,
    ToolCompleted,
    ToolStarted,
    encode_event,
    read_stream,
)


def test_encode_event_carries_index_tag_and_payload():
    line = encode_event(3, TextDelta("hi"))

    assert json.loads(line) == {"i": 3, "t": "text", "v": {"text": "hi"}}


def test_tool_events_encode_call_identity_and_previews():
    started = json.loads(
        encode_event(0, ToolStarted("call-1", "search_corpus", "Kafka"))
    )
    done = json.loads(
        encode_event(1, ToolCompleted("call-1", "search_corpus", "3 hits", True))
    )

    assert started["v"] == {
        "callId": "call-1",
        "name": "search_corpus",
        "argsPreview": "Kafka",
    }
    assert done["v"] == {
        "callId": "call-1",
        "name": "search_corpus",
        "resultPreview": "3 hits",
        "ok": True,
    }


def test_null_sink_discards_and_close_is_idempotent():
    sink = NullSink()

    sink.emit(TextDelta("x"))
    sink.close()
    sink.close()


def test_console_sink_writes_text_tools_and_one_trailing_newline():
    written: list[str] = []
    sink = ConsoleStreamSink(written.append)

    sink.emit(TextDelta("hello "))
    sink.emit(ToolStarted("call-1", "search_corpus", "Kafka"))
    sink.emit(TextDelta("world"))
    sink.close()
    sink.close()

    assert "hello " in written
    assert "world" in written
    assert any("search_corpus" in row for row in written)
    assert written.count("\n") == 1


def test_run_sink_round_trips_events_in_order(tmp_path):
    path = tmp_path / "run.stream.ndjson"
    sink = RunStreamSink(path, flush_chars=1)

    sink.emit(TextDelta("a"))
    sink.emit(ToolStarted("call-1", "t", "x"))
    sink.emit(TextDelta("b"))
    sink.emit(Completed())
    sink.close()

    rows = list(read_stream(path))
    assert [(index, tag) for index, tag, _ in rows] == [
        (0, "text"),
        (1, "tool_started"),
        (2, "text"),
        (3, "completed"),
    ]


def test_run_sink_coalesces_consecutive_text_deltas(tmp_path):
    path = tmp_path / "run.stream.ndjson"
    sink = RunStreamSink(path, flush_chars=1000, flush_interval=1000)

    sink.emit(TextDelta("a"))
    sink.emit(TextDelta("b"))
    sink.emit(TextDelta("c"))
    sink.close()

    assert [(tag, payload) for _, tag, payload in read_stream(path)] == [
        ("text", {"text": "abc"})
    ]


def test_non_text_event_flushes_pending_text_first(tmp_path):
    path = tmp_path / "run.stream.ndjson"
    sink = RunStreamSink(path, flush_chars=1000, flush_interval=1000)

    sink.emit(TextDelta("a"))
    sink.emit(Notice("dropped"))
    sink.close()

    assert [tag for _, tag, _ in read_stream(path)] == ["text", "notice"]


def test_run_sink_ignores_events_after_terminal_and_repeated_close(tmp_path):
    path = tmp_path / "run.stream.ndjson"
    sink = RunStreamSink(path, flush_chars=1)

    sink.emit(TextDelta("a"))
    sink.emit(Completed())
    sink.emit(TextDelta("must not leak"))
    sink.emit(Failed("late"))
    sink.close()
    sink.close()

    assert [tag for _, tag, _ in read_stream(path)] == ["text", "completed"]


def test_read_stream_offset_returns_only_the_tail(tmp_path):
    path = tmp_path / "run.stream.ndjson"
    sink = RunStreamSink(path, flush_chars=1)
    for letter in "abcd":
        sink.emit(TextDelta(letter))
    sink.close()

    assert [index for index, _, _ in read_stream(path, offset=2)] == [2, 3]


def test_read_stream_missing_file_is_empty_not_an_error(tmp_path):
    assert list(read_stream(tmp_path / "absent.ndjson")) == []


def test_read_stream_skips_torn_or_malformed_rows(tmp_path):
    path = tmp_path / "run.stream.ndjson"
    path.write_text(
        "\n".join(
            [
                encode_event(0, TextDelta("a")),
                '{"i": 1, "t": "text", "v": []}',
                '{"i": "2", "t": "text", "v": {}}',
                '{"i": 3, "t": 4, "v": {}}',
                '{"i": 4, "t"',
            ]
        ),
        encoding="utf-8",
    )

    assert list(read_stream(path)) == [(0, "text", {"text": "a"})]


def test_failed_and_reasoning_events_encode_their_payloads():
    failed = json.loads(encode_event(0, Failed("boom", "PROVIDER_ERROR")))
    reasoning = json.loads(encode_event(1, ReasoningDelta("why")))

    assert failed == {
        "i": 0,
        "t": "failed",
        "v": {"message": "boom", "code": "PROVIDER_ERROR"},
    }
    assert reasoning["t"] == "reasoning"
