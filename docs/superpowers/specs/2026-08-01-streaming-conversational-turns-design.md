# Streaming conversational turns for the Profile Coach and Mock Interviewer

**Date:** 2026-08-01
**Status:** Approved, pending implementation plan
**Scope:** `llm_runner.py`, `sessions/`, `profile/coach.py`, `interview/agent.py`,
`services/profile_coach.py`, `services/mock_interview.py`, `api/runs/`,
`api/routers/runs.py`, `cli.py`, `web/src/components/chat/`,
`web/src/features/coach/`, `web/src/features/interview/`

**Sequencing:** This is spec 1 of 2. Spec 2 (a conversational Source/Search Scout
that refines search keywords and source companies across multiple turns) depends
on the substrate built here and is deliberately not designed in this document.

## Correctness clarifications (implementation-authoritative)

The implementation review found several lifecycle details that the original
design left implicit. These rules are authoritative for this spec:

1. **The service owns the terminal event.** `AgentRunner.stream()` reports the
   provider/Agno terminal result to its caller, but the API sink does not emit
   `completed` until formatting, validation, and the durable session mutation
   have all succeeded. Any exception or cancellation emits exactly one `failed`
   terminal event instead. This prevents the SSE reader from closing before a
   durable notice or turn exists and makes the bubble/refetch hand-off reliable.
2. **A failed or cancelled stream never persists a partial turn.** A failure at
   any point after the first visible delta is surfaced in place and the service
   raises before `apply_turn_delta`, `apply_answer_delta`, `create_session`, or
   `end_session`. Retries remain pre-visible-output only.
3. **Every streamed event is a cancellation checkpoint.** The turn service calls
   the run reporter's public `checkpoint()` while consuming the provider stream.
   This is what makes Stop cooperative at token/tool-event granularity. It cannot
   interrupt a provider while no event is arriving, but it stops before the next
   event is shown or any session mutation is committed.
4. **Agno events are matched by their enum value, not `str(event)`.** In pinned
   Agno 2.8.2, `str(RunEvent.run_content)` is `RunEvent.run_content`, while
   `.value` is `RunContent`. Tests use real Agno event enums or faithful enum
   doubles so a string-only fake cannot conceal this mismatch. The terminal
   `RunOutput` is carried by the internal `Completed` event; mutable
   `AgentRunner.last_output` state is unnecessary.
5. **Tool events carry `call_id`.** A name is not an identity when tools can run
   more than once or in parallel. Started/completed events and the TypeScript
   reducer match on Agno's `tool_call_id`, with the name retained for display.
6. **Stream terminals mirror run terminals.** If the stream file cannot record
   its terminal event, the SSE grace fallback maps `done` to `completed` and
   maps `error`/`cancelled` to `failed` with the run's error code. It must never
   turn a failed worker into a successful conversation. Run cleanup and sweeping
   remove both the JSON record and its `.stream.ndjson` sibling.
7. **Only draft-integrity failures are droppable.** Missing/incomplete note
   content, missing quotes, and fabricated quotes raise `DraftRejected`.
   Unknown/closed topics, duplicate drafts, invalid updates, and agenda overflow
   remain structural `TurnRejected` failures even in the lenient retry.
8. **The browser validates the hand-written SSE payload at the boundary.**
   Malformed or unknown events are ignored without mutating the cursor or
   throwing from React. Hook state resets whenever `runId` changes, transport
   reconnects use `offset=lastIndex+1`, and pending reconnect timers are cleared
   on cleanup.
9. **Refresh recovery uses the existing run registry.** Conversation runs carry
   `meta.sessionId` (where a session already exists), and pages select the active
   run by kind plus session id after `useRehydrateRuns()` restores the run store.
   Replaying from offset zero after a full page refresh is valid reconstruction;
   transport reconnects within the mounted page resume from the next offset.
10. **Stop and retry discard synthetic state immediately.** Stop requests run
    cancellation, clears the partial assistant bubble, and leaves the durable
    transcript unchanged. Retry starts with a fresh run/cursor and reuses the
    same user input. A synthetic bubble is hidden synchronously as soon as the
    durable turn count advances, then cleaned up in an effect, so it is never
    rendered beside its durable replacement.
11. **Existing transcript affordances remain.** Coach research-action cards,
    draft cards, recap/impact panels, rails, setup dialogs, and the interview
    debrief are preserved. Shared chat primitives replace only message rendering
    and composition; durable research actions remain adjacent to their turn.

---

## Problem

The Profile Coach and Mock Interviewer are already multi-turn, but every turn is
a silent block of dead time. `POST .../messages` returns `202` with a run id; a
worker runs a persona agent (which calls corpus tools), then a cheap formatter
agent, then validation; the client watches `GET /api/runs/{id}/events`, which
projects a `RunOut` from a JSON file polled every 0.5s. The user sees a spinner
and a phase label — "Coach is thinking" — for the entire turn, then the whole
reply appears at once. A coach turn that calls two corpus tools can run 30+
seconds.

Three concrete costs:

1. **No incremental output.** The reply is a field of a structured object that
   does not exist until the whole pipeline finishes.
2. **No visible progress.** Corpus tool calls happen inside the persona agent and
   are invisible until they are summarized post-hoc by `ResearchActionCard`.
3. **Stop does not work.** `RunManager`'s cancellation is cooperative and only
   fires at a `reporter.begin`/`step` checkpoint. A turn is one long blocking LLM
   call with no checkpoints in the middle, so there is nothing to cancel against.

A fourth cost is structural rather than perceptual. `normalize_turn` is
all-or-nothing: a single fabricated quote in a draft note raises `TurnRejected`
and destroys the **entire** turn, so the user loses the coach's response along
with the bad draft.

## Why the message is not simply streamable today

The text the user reads is not the text the persona agent writes — nominally.
`build_coach_agent` produces free-form notes; `build_coach_formatter_agent`
projects them into `CoachTurn.message`. But the formatter's own instructions are:

> "Copy only explicit message, action, topic updates, draft fields, quotes, and
> research actions into the schema." / "Invent nothing."

So the prose already originates in the persona agent. The formatter is a
projector, not an author. Streaming the persona agent is therefore not a
semantic change to the message — it removes a copy step.

This also settles which agent to stream. Streaming the formatter (the cheap,
fast, last step) would leave the user watching a spinner through the entire
tool-using phase and stream only the final second.

## Non-goals

- Edit/resend and ChatGPT-style branching. ADR 0006 sessions are an append-only
  transcript, and the verbatim-quote gate reads back over it.
- Streaming the Source/Search Scouts (spec 2).
- Streaming tailor, cover-letter, pull, or discover runs.
- Persisting tool/reasoning parts into the durable transcript. They are progress
  affordances, not history. (Validation notices are the exception and _are_
  persisted — see the validation split.)
- Multi-process stream fanout. Railway is single-service, single-volume.
- Replacing `GET /api/runs/{id}/events`. It is the `RunOut` projection every run
  kind uses and is unchanged.

---

## Architecture

### 1. A streaming seam in `llm_runner.py`

`AgentRunner` gains a third method beside `run`/`arun`:

```python
def stream(self, prompt: str) -> Iterator[StreamEvent]: ...
```

It keeps the identical envelope as `run`: `refresh_agent_api_key`,
`enforce_agent_budget`, and `record_call` against the final `RunOutput` (agno's
`yield_run_output` makes the terminal `RunOutput` the last yielded item). Budget
enforcement stays _before_ the first provider call, so quota and shared-key
gating are unaffected.

It yields **our own** dataclasses, never agno types — the same reason
`build_model` is the only place that knows about provider SDKs:

```python
TextDelta(text)
ReasoningDelta(text)
ToolStarted(name, args_preview)
ToolCompleted(name, result_preview, ok)
Completed(response)          # carries the final RunOutput
Failed(error, code)
```

Verified against the pinned runtime (**agno 2.8.2**): `Agent.run` accepts
`stream` and `stream_events`, and `RunEvent` includes `RunContent`,
`ToolCallStarted`, `ToolCallCompleted`, `ToolCallError`, `ReasoningContentDelta`,
`RunCompleted`, `RunError`, and `RunCancelled`. No agno upgrade is required.

**Retry policy changes, and it matters.** `run`/`arun` retry any transient error
up to `Settings.llm_retries`. `stream` retries **only before the first token**.
Once bytes have reached the user, a silent retry would duplicate visible text, so
a post-first-token transient failure yields `Failed` and the in-place retry
affordance takes over.

### 2. The sink protocol — `sessions/stream.py`

```python
class StreamSink(Protocol):
    def emit(self, event: StreamEvent) -> None: ...
```

| Implementation      | Used by                           | Behavior                                             |
| ------------------- | --------------------------------- | ---------------------------------------------------- |
| `RunStreamSink`     | API run workers                   | Appends ndjson to `data/runs/{run_id}.stream.ndjson` |
| `ConsoleStreamSink` | `resume-tailor-harness profile coach`      | Prints text deltas and tool chips to stdout          |
| `NullSink`          | tests, non-conversational callers | Discards                                             |

`RunStreamSink` resolves its path through `RunManager`'s registered root for the
run (the same mechanism `_root_for` uses), so the stream file lands under the
**same tenant root** as the run record and inherits tenant confinement. It is
never addressed by a client-supplied path.

Appends use `open(..., 'a')` + flush — deliberately _not_ `progress.py`'s
atomic-replace path, which would be both slow and unreadable if applied per
chunk. Events batch on a ~80ms / N-character boundary so a fast model does not
produce one syscall per token.

The stream file is cleaned alongside the run record; it is ephemeral by design.

### 3. Reader — `GET /api/runs/{run_id}/stream?offset=N`

A new SSE endpoint beside the existing `/events`, sharing its auth guard
(`get_sse_user_context`). Each ndjson line carries a monotonic index `i` starting
at 0. `offset=N` means "send me events with `i >= N`", so a client that has
consumed through index `k` reconnects with `offset=k+1`. `offset=0` (the default)
replays the turn from its beginning. The endpoint closes on the terminal event.

Offset resume is the reason a file was chosen over an in-memory buffer: a coach
turn can run 30+ seconds, which is precisely when a user refreshes. On reconnect
the client replays from its last index rather than losing the partial answer.

A missing stream file for a live run yields an empty tail (not a 404) — the
worker may not have emitted its first event yet.

### 4. Where the visible message comes from

The persona prompt gains a two-part output contract:

```
<user-facing prose>
---METADATA---
action: draft
topic: t3
...
```

Deltas up to `---METADATA---` are emitted to the sink. Everything after it is
buffered silently. The **complete** output (prose + metadata) still goes to the
formatter, whose instructions and schema are unchanged.

The stored turn text is the **streamed prose, verbatim**. When a stream produced
prose, the formatter's `message` field is ignored — which eliminates formatter
drift on the visible message entirely.

Two robustness rules:

- **Delimiter holdback.** The emitter withholds a trailing window (32 characters,
  the delimiter length plus margin) before flushing, so a delimiter split across
  chunk boundaries never leaks a partial `---METADAT` into the bubble. The
  holdback is flushed on stream completion if no delimiter was found.
- **Missing delimiter degrades, does not fail.** If the model never emits the
  delimiter, the entire output is treated as the message and the formatter
  extracts structure from it exactly as it does today.

### 5. Kill switch

`Settings.stream_enabled` (default `true`) falls back to today's blocking path:
the sink becomes `NullSink`, `AgentRunner.run` is used instead of `stream`, and
the formatter's `message` is authoritative again. The message-source inversion in
§4 is a real behavior change; one flag makes it revertible in production without
a redeploy.

---

## Validation split

`normalize_turn` (both the coach's and the interviewer's) stops being
all-or-nothing. Rejections are classified:

| Class          | Causes                                                                                                | Handling                                                                                                                                                                                            |
| -------------- | ----------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Structural** | unknown `topic_id`, invalid topic update, agenda cap exceeded, empty message, reserved `recap` action | Retry the **formatter only** (cheap tier, ~1s, no re-stream). On a second failure, store the turn with the streamed prose, fall back to the session's current open topic, and attach a notice.      |
| **Draft**      | missing quotes, fabricated quote, incomplete draft note                                               | One formatter retry (the notes may have carried a verbatim quote the formatter paraphrased), then **drop the draft**, attach `notice: "note not attached — quote check failed"`, and keep the turn. |

`format_with_retry` in `sessions/turns.py` remains the single seam; it grows the
classification and the degradation return rather than being duplicated per stack.
`TurnRejected` gains a `DraftRejected` subclass so classification is a type
check, not string matching.

Under `stream_enabled=false` there is no streamed prose, so structural
degradation stores the **formatter's** `message` instead. Everything else about
the split is identical in both modes — the degradation behavior is not tied to
streaming, only its text source is.

**Notices are durable.** A notice explains a _missing_ draft note, so it must
survive a page refresh; it is stored on the turn record (`CoachTurnRecord.notice`,
`InterviewTurnRecord.notice`) and projected through the session view, not merely
emitted as a stream part. This is the one exception to the non-goal above: tool
and reasoning parts stay ephemeral, notices do not.

**Fact-lock is strictly unchanged.** `approve_draft` remains the only path into
the corpus and still requires a draft that passed the verbatim-quote gate. A
dropped draft simply never reaches it. The net effect is that a bad quote stops
destroying the coach's response — a strictly smaller blast radius than today.

The interviewer's `normalize_turn` (followup counts, plan items) gets the same
structural treatment. **The debrief is not streamed as prose** — it is a
structured scorecard — and keeps its current path, gaining only phase events.

Opening turns and recap turns stream, since both produce a user-facing message.

---

## Interface

### Chat primitives

```
web/src/components/chat/
  ChatThread.tsx        · scroll anchoring + jump-to-latest pill
  ChatMessage.tsx       · role bubble, renders parts in arrival order
  parts/TextPart.tsx    · streaming markdown + caret
  parts/ToolPart.tsx    · collapsible activity chip
  parts/ReasoningPart.tsx
  parts/NoticePart.tsx  · degradation notices from the validation split
  ChatComposer.tsx      · textarea, send/stop, TranscribeButton
  useChatStream.ts      · EventSource + offset resume → parts[]
```

The parts model — a message as an ordered list of typed parts (`text`,
`reasoning`, `tool`, `notice`) rendered in arrival order — is the pattern every
mainstream chat UI library converged on ([assistant-ui](https://www.assistant-ui.com/),
Vercel's AI Elements, [shadcn-chatbot-kit](https://github.com/Blazity/shadcn-chatbot-kit),
[shadcn-chat](https://github.com/jakobhoeg/shadcn-chat)). We adopt the pattern,
not the dependency: these components are built on the Base UI / shadcn primitives
already in the repo, avoiding a second runtime layer that would have to be
adapted to the ndjson transport, and giving spec 2's Scout a ready surface.

`useChatStream(runId)` returns `{ parts, status, stop, retry }`.

### Behaviors in scope

- **Stop generating.** Newly feasible: each streamed chunk is a cancellation
  checkpoint. A stopped turn is **discarded** — the session transcript is left
  exactly as it was, so there is no half-turn to reason about.
- **Scroll anchoring + jump-to-latest.** Track whether the viewport is within a
  threshold of the bottom; autoscroll **only while stuck**; release permanently
  the moment the user scrolls up, showing a floating pill. Never
  `scrollIntoView` per token.
- **Live tool and reasoning disclosure.** Tool calls render as collapsible chips
  inline; reasoning renders as a collapsed disclosure where the provider exposes
  it.
- **In-place retry.** A turn that errors mid-stream offers retry on the message
  itself rather than today's page-level alert. It re-sends the same user message
  and discards the failed partial.

### Surface differences

**The interviewer suppresses reasoning parts.** The mock interview stays in
character with no mid-session coaching; showing the candidate the interviewer's
private reasoning hands them exactly what the question is probing for. Tool chips
remain visible ("reading the job description"). The Coach, whose job is to teach
while probing, shows both.

### Bubble lifecycle

The streaming assistant bubble is synthetic and keyed by `runId`. It is replaced
by the durable turn only **after** the session refetch resolves, so there is no
frame in which both or neither is rendered.

`CoachPage` and `InterviewPage` keep everything around the transcript —
`AgendaRail`, `DraftNoteCard`, `ImpactCard`, `SessionsRail`, the setup dialogs.
Only the transcript region is swapped for `<ChatThread>`.

---

## CLI

`resume-tailor-harness profile coach` calls the service functions synchronously with no
run and no reporter. The service functions take an optional `sink: StreamSink`
parameter; the API passes `RunStreamSink`, the CLI passes `ConsoleStreamSink`.
Both clients therefore exercise the **same** code path through a turn, so the CLI
stops being the place where a streaming regression can hide.

---

## Contracts

The new SSE route regenerates `contracts/openapi.json` → `contracts/ts/api.ts`
via `bash scripts/gen_ts_client.sh`; `tests/api/test_openapi_contract.py` is the
drift gate.

OpenAPI cannot describe an SSE event body, so the `StreamEvent` union gets a
hand-written TypeScript type plus a **parity test** asserting that the Python
dataclass tags and the TypeScript union agree. Without it, that is exactly where
drift would hide.

---

## Testing

The suite stays offline: no API key, no network, no browser.

- `FakeStreamingRunner` yielding scripted `StreamEvent` sequences — the streaming
  analogue of the existing agent fakes.
- `RunStreamSink` round-trip: write events → tail from offset 0 → identical
  sequence; tail from a mid offset → tail only.
- Delimiter split across chunk boundaries yields no partial delimiter in the
  emitted prose; delimiter entirely absent yields the whole output as the message.
- Degradation: a fabricated quote drops the draft, keeps the turn, and leaves the
  corpus asserted untouched (`facts.json` and the source manifest unchanged).
- Structural degradation: two formatter rejections store the streamed prose
  against the session's current open topic with a notice.
- Notice persistence: a dropped draft's notice survives a session reload (it is
  on the turn record, not only in the ephemeral stream).
- Stop mid-stream leaves the session transcript byte-identical to before the turn.
- Retry policy: a transient error before the first token retries; after the first
  token it surfaces as `Failed`.
- `stream_enabled=false` reproduces today's behavior exactly (existing coach and
  interview tests pass unchanged under the flag).
- Web: fake `EventSource`; parts render in arrival order; the anchor releases on
  user scroll and the pill appears; stop issues a cancel; the synthetic bubble is
  replaced without a flicker frame.
- Interview surface: reasoning parts are not rendered.

---

## Risks

| Risk                                                     | Mitigation                                                                                                   |
| -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| Model ignores the metadata delimiter                     | Whole output becomes the message; formatter extracts structure as today                                      |
| Streamed prose quality differs from the formatter's copy | The formatter was already instructed to copy verbatim; `stream_enabled=false` reverts                        |
| Per-chunk file IO cost                                   | Batched on an ~80ms / N-char boundary                                                                        |
| Mid-turn refresh loses the answer                        | Offset resume replays from the client's last index                                                           |
| A provider streams poorly                                | `stream_enabled=false` kill switch, per-deploy                                                               |
| Windows file sharing during append + tail                | Reader opens read-only and tolerates a short read; `progress.py` already carries the bounded-retry precedent |
