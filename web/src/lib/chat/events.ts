/** Hand-written SSE contract; Python parity is enforced by a backend test. */
export const STREAM_EVENT_TAGS = [
  "text",
  "reasoning",
  "tool_started",
  "tool_completed",
  "notice",
  "settled",
  "completed",
  "failed",
] as const;

export type StreamEventTag = (typeof STREAM_EVENT_TAGS)[number];

export type StreamEvent =
  | { i: number; t: "text"; v: { text: string } }
  | { i: number; t: "reasoning"; v: { text: string } }
  | {
      i: number;
      t: "tool_started";
      v: { callId: string; name: string; argsPreview: string };
    }
  | {
      i: number;
      t: "tool_completed";
      v: {
        callId: string;
        name: string;
        resultPreview: string;
        ok: boolean;
      };
    }
  | { i: number; t: "notice"; v: { message: string } }
  | { i: number; t: "settled"; v: Record<string, never> }
  | { i: number; t: "completed"; v: Record<string, never> }
  | { i: number; t: "failed"; v: { message: string; code: string } };

export type ChatPart =
  | { kind: "text"; text: string }
  | { kind: "reasoning"; text: string }
  | {
      kind: "tool";
      callId: string;
      name: string;
      argsPreview: string;
      resultPreview: string;
      ok: boolean;
      done: boolean;
    }
  | { kind: "notice"; message: string };

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function strings(value: Record<string, unknown>, ...keys: string[]): boolean {
  return keys.every((key) => typeof value[key] === "string");
}

/** Validate untrusted EventSource JSON before it can move the resume cursor. */
export function parseStreamEvent(value: unknown): StreamEvent | null {
  if (!record(value) || !Number.isInteger(value.i) || (value.i as number) < 0) return null;
  if (!record(value.v) || typeof value.t !== "string") return null;
  const v = value.v;
  switch (value.t) {
    case "text":
    case "reasoning":
      break;
    case "tool_started":
      if (strings(v, "callId", "name", "argsPreview")) return value as StreamEvent;
      return null;
    case "tool_completed":
      if (strings(v, "callId", "name", "resultPreview") && typeof v.ok === "boolean") {
        return value as StreamEvent;
      }
      return null;
    case "notice":
      if (typeof v.message === "string") return value as StreamEvent;
      return null;
    case "settled":
    case "completed":
      return value as StreamEvent;
    case "failed":
      if (strings(v, "message", "code")) return value as StreamEvent;
      return null;
    default:
      return null;
  }
  return typeof v.text === "string" ? (value as StreamEvent) : null;
}

export function reduceEvent(parts: ChatPart[], event: StreamEvent): ChatPart[] {
  const last = parts.at(-1);
  if (event.t === "text" || event.t === "reasoning") {
    const kind = event.t;
    if (last?.kind === kind) {
      return [...parts.slice(0, -1), { kind, text: last.text + event.v.text }];
    }
    return [...parts, { kind, text: event.v.text }];
  }
  if (event.t === "tool_started") {
    return [
      ...parts,
      {
        kind: "tool",
        callId: event.v.callId,
        name: event.v.name,
        argsPreview: event.v.argsPreview,
        resultPreview: "",
        ok: true,
        done: false,
      },
    ];
  }
  if (event.t === "tool_completed") {
    const index = parts.findIndex(
      (part) => part.kind === "tool" && part.callId === event.v.callId && !part.done,
    );
    if (index < 0) return parts;
    const next = [...parts];
    const tool = parts[index];
    if (tool.kind !== "tool") return parts;
    next[index] = {
      ...tool,
      name: event.v.name,
      resultPreview: event.v.resultPreview,
      ok: event.v.ok,
      done: true,
    };
    return next;
  }
  if (event.t === "notice") {
    return [...parts, { kind: "notice", message: event.v.message }];
  }
  return parts;
}
