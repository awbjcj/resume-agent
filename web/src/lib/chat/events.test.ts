import { describe, expect, it } from "vitest";

import { parseStreamEvent, reduceEvent, type ChatPart } from "./events";

describe("chat stream events", () => {
  it("coalesces text while preserving tool order", () => {
    let parts: ChatPart[] = [];
    parts = reduceEvent(parts, { i: 0, t: "text", v: { text: "a" } });
    parts = reduceEvent(parts, { i: 1, t: "text", v: { text: "b" } });
    parts = reduceEvent(parts, {
      i: 2,
      t: "tool_started",
      v: { callId: "c1", name: "search", argsPreview: "query" },
    });
    parts = reduceEvent(parts, { i: 3, t: "text", v: { text: "c" } });
    expect(parts.map((part) => part.kind)).toEqual(["text", "tool", "text"]);
    expect(parts[0]).toEqual({ kind: "text", text: "ab" });
  });

  it("completes the matching tool call id, not another call of the same name", () => {
    let parts: ChatPart[] = [];
    for (const callId of ["c1", "c2"]) {
      parts = reduceEvent(parts, {
        i: parts.length,
        t: "tool_started",
        v: { callId, name: "search", argsPreview: callId },
      });
    }
    parts = reduceEvent(parts, {
      i: 2,
      t: "tool_completed",
      v: { callId: "c1", name: "search", resultPreview: "done", ok: true },
    });
    expect(parts[0]).toMatchObject({ callId: "c1", done: true });
    expect(parts[1]).toMatchObject({ callId: "c2", done: false });
  });

  it("rejects malformed browser input", () => {
    expect(parseStreamEvent({ i: "0", t: "text", v: { text: "x" } })).toBeNull();
    expect(parseStreamEvent({ i: 0, t: "text", v: { text: 1 } })).toBeNull();
    expect(parseStreamEvent({ i: 0, t: "future", v: {} })).toBeNull();
    expect(parseStreamEvent({ i: 0, t: "completed", v: {} })).not.toBeNull();
  });
});
