import re
from pathlib import Path

from resume_agent.sessions.stream import (
    Completed,
    Failed,
    Notice,
    ReasoningDelta,
    TextDelta,
    ToolCompleted,
    ToolStarted,
)


def test_typescript_tags_match_python_events():
    source = Path("web/src/lib/chat/events.ts").read_text(encoding="utf-8")
    block = re.search(r"STREAM_EVENT_TAGS\s*=\s*\[(.*?)\]", source, re.S)
    assert block
    types = (
        TextDelta,
        ReasoningDelta,
        ToolStarted,
        ToolCompleted,
        Notice,
        Completed,
        Failed,
    )
    assert set(re.findall(r'"([a-z_]+)"', block.group(1))) == {
        event.tag for event in types
    }
