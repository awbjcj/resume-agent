# Streaming Latency and Fluency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a Coach / Interviewer / Scout turn _feel_ as fast as the provider actually is. Cut ~200–330 ms of self-inflicted transport latency per visible chunk, remove ~34 characters of permanent lag behind the model's cursor, stop the caret blinking through a 1–4 s formatter call the user cannot see, and make the browser's cost-per-delta O(new text) instead of O(whole transcript).

**Non-goal:** making the _model_ faster. Tier selection, reasoning effort, and provider choice are already governed by `llm_runner.build_model` and are out of scope except for Task 8 (prompt caching), which is a TTFT change, not a quality change.

**Architecture:** The durable NDJSON run log stays exactly where it is — it is what makes a mid-turn refresh resumable, and nothing here weakens that. What changes is that the log stops being the _notification_ mechanism as well as the _durability_ mechanism. A per-run notifier lets the SSE generator wake on append instead of on a 250 ms timer, with the existing poll retained as the fallback path. A new non-terminal `settled` event separates "the reply is complete" from "the run is complete", so the UI can stop pretending the model is still typing while a formatter finishes. `ProseEmitter`'s fixed holdback becomes a candidate-prefix holdback, so it withholds text only when the tail could genuinely still become a metadata boundary. On the web side, markdown parsing is split at block boundaries and memoised so a delta re-parses one paragraph, not the thread.

**Tech Stack:** Python 3.12 · FastAPI · sse-starlette · agno 2.6.x/2.8.x · pytest · React 19 · TanStack Query · react-markdown 10 · Vitest

---

## Global Constraints

- **Branch:** create `perf/streaming-fluency` from the current protected base branch. At implementation time (2026-08-02), neither the local checkout nor `origin` had a `dev` branch despite the stale guidance in `CLAUDE.md`, so this work branches from `main` rather than inventing an unavailable base.
- **Tests run offline.** No API key, no network, no browser. Every agent is faked. Python: `.venv/Scripts/python.exe -m pytest`. Lint: `ruff check`. Web: `cd web && npm test`, `cd web && npm run lint`.
- **Measure before and after every task that claims a latency number.** Task 1 builds the harness; no later task may be marked done without its before/after row filled in. A task whose measurement shows no improvement gets reverted, not merged.
- **The wire contract is generated, not hand-edited.** Adding the `settled` event touches `sessions/stream.py`, `web/src/lib/chat/events.ts`, and the parity test that pins them together. Any route or schema change requires `bash scripts/gen_ts_client.sh`; `tests/api/test_openapi_contract.py` is the drift gate.
- **Durability and resume are invariants.** After every change: a client that disconnects mid-turn and reconnects with `?offset=N` still receives every event from `N` onward, in order, exactly once. `StreamTail` must continue to stop at the last complete newline so a row mid-`flush()` is never parsed truncated.
- **Exactly one terminal event per run.** `with_conversation_stream` remains the only writer of `Completed` / `Failed`. `settled` is explicitly _not_ terminal and must not appear in `TERMINAL_TAGS`.
- **Never weaken the metadata boundary.** `_BOUNDARY` in `sessions/turns.py` exists because a model that skips the `---METADATA---` sentinel would otherwise dump `action:` / `draft:` / `PROPOSE |` rows into the chat window. Task 3 may only change _how much is withheld while waiting_, never _what counts as a boundary_. Leaking one metadata line is a worse regression than the latency it buys back.
- **Never import a provider SDK outside `build_model`.**

---

## Measured baseline (fill in during Task 1)

The numbers below are **derived from the constants in the code**, not yet measured.
Task 1 replaces every "derived" cell with an observed p50/p95. Do not cite these as
measurements until it has.

| Stage                               | Source                                                              | Derived cost                            | Measured p50 | Measured p95 |
| ----------------------------------- | ------------------------------------------------------------------- | --------------------------------------- | ------------ | ------------ |
| Prose holdback behind model cursor  | `sessions/turns.py:85` (`MARKER_MAX_LEN` = 32 → holdback 34)        | 34 chars ≈ 8 tokens                     |              |              |
| Sink batch window                   | `sessions/stream.py:165` (`flush_interval=0.08`, `flush_chars=240`) | 0–80 ms                                 |              |              |
| Log append syscalls                 | `sessions/stream.py:209` (open/write/flush/close per row)           | 1 open+close per row                    |              |              |
| **SSE poll wait**                   | `api/runs/stream_sse.py:19` (`poll_interval=0.25`)                  | **0–250 ms, mean 125**                  |              |              |
| Terminal grace (fallback path only) | `api/runs/stream_sse.py:11` (`_GRACE_POLLS=4`)                      | up to 1 s                               |              |              |
| Browser render per event            | `ChatThread`/`ChatMessage`/`TextPart`, no `memo`                    | O(whole transcript)                     |              |              |
| **Post-prose dead tail**            | `api/runs/conversation.py:34` + `sessions/turns.py:211`             | **1 full formatter call (+1 on retry)** |              |              |
| Per-turn stream handshake           | `web/src/lib/chat/useChatStream.ts:84`                              | 1 extra POST round trip                 |              |              |

**Infrastructure floor today:** ≈ 205 ms mean / 330 ms worst added to every visible
chunk, _plus_ 34 characters of permanent lag, _plus_ a dead tail of one whole LLM
call at the end of every turn.

---

## Task 1 — Build the measurement harness (do this first)

Everything after this is guesswork without it.

- [ ] Add `tests/perf/test_stream_latency.py` (offline, deterministic): a fake agent that yields N `TextDelta`s on a controlled clock, driven through the **real** `RunStreamSink` and the **real** `stream_events` generator via `httpx` ASGI transport. Record, per event, the interval between "sink received it" and "SSE yielded it". Assert on structure, not wall-clock: with a notifier present (Task 2) the generator must not have slept at all. Wall-clock assertions here will be flaky in CI — use an injected clock.
- [ ] Add `scripts/stream_latency.py`: an opt-in live probe (requires a real key, never runs in CI) that drives one Coach turn and reports **TTFT**, inter-chunk gap p50/p95, total events, total log bytes, and the wall-clock split between _prose end_ and _run completed_. This last number is the Task 4 justification.
- [ ] Web: add a render-count harness to `web/src/lib/chat/useChatStream.test.ts` (or a new `ChatThread.perf.test.tsx`) that feeds K events into a thread of M durable messages and counts `TextPart` renders. Today this is O(K·M); Task 6 makes it O(K).
- [ ] Fill the **Measured baseline** table above. Commit it. This is the row every later task is compared against.

**Verification:** `.venv/Scripts/python.exe -m pytest tests/perf -q` passes; the baseline table has no empty measured cells.

---

## Task 2 — Wake the SSE generator on append instead of on a timer

**The single largest infrastructure win.** ~125 ms mean / 250 ms worst removed from every chunk.

The worker is a thread (`ThreadPoolExecutor`, `manager.py:165`); the SSE generator is
a coroutine. The bridge is `loop.call_soon_threadsafe`, captured when the SSE
generator starts — never captured in the worker, which has no running loop.

- [ ] Add a `StreamNotifier` to `api/runs/manager.py` (or a new `api/runs/notify.py`): a per-run object holding a set of `asyncio.Event`s plus the loop each was created on. `notify()` is thread-safe and fans out via `call_soon_threadsafe`; `subscribe()` returns an event a generator can await; unsubscribe on generator close.
- [ ] Give `RunStreamSink` an optional `on_append: Callable[[], None]` invoked after each row is durably written (after `flush()`, never before — a reader woken early would find nothing and busy-spin). `with_conversation_stream` wires it to `manager.notifier(run_id).notify`.
- [ ] Rewrite the `stream_events` loop: drain `tail.read(cursor)`; if it produced nothing, `await asyncio.wait_for(event.wait(), timeout=poll_interval)` instead of `await asyncio.sleep(poll_interval)`. **Keep the timeout.** The poll remains the correctness path — the notifier is a latency optimisation, and a dropped notification must cost 250 ms, not a hang.
- [ ] Drop `poll_interval` for the _terminal grace_ path to 0.05 s. It only runs after the manager already reports a terminal state, so the four polls exist to catch a straggling row, not to wait on work.

**Risks:** a generator that outlives its loop must not leave a dangling event —
unsubscribe in a `finally`. Multiple concurrent subscribers to one run (two tabs)
must each get woken.

**Verification:** the Task 1 harness shows zero sleeps on the happy path; kill the
notifier in a test and confirm the generator still delivers every event via the
timeout path; the existing `tests/api/test_run_stream_route.py` suite stays green
unmodified.

---

## Task 3 — Hold back a boundary _candidate_, not a fixed 34 characters

`ProseEmitter` withholds `MARKER_MAX_LEN + 2` = 34 characters at all times, so the
visible text sits roughly eight tokens behind the model forever. But 34 is the
length of the _longest possible_ boundary; the tail only needs withholding when it
could actually still grow into one.

A boundary can only begin at: a blank line followed by a block key or a `PROPOSE|AVOID`
row, or a run of emphasis/dash characters that could become `---METADATA---`. If the
pending tail contains no such candidate start, **all of it is safe to flush**.

- [ ] Replace the fixed-window flush in `ProseEmitter.feed` with a `_safe_prefix_len(pending)` helper: return the index of the earliest position from which a boundary match could still complete, or `len(pending)` when none exists. Flush everything before it.
- [ ] Keep `MARKER_MAX_LEN` as the hard ceiling on how far back a candidate may start — the helper must never scan unboundedly into the buffer.
- [ ] Extend `tests/test_turn_prose.py`: prose ending mid-word flushes fully; prose ending in `\n\n` withholds from the blank line; prose ending in `\n\n--` withholds from the blank line; a boundary split across three deltas is still caught and still truncates at the right place; **every existing leak test still passes** (this is the gate — re-run the `PROPOSE |`, bare-`---`-rule, and `**Action:**`-mid-sentence cases explicitly).

**Design note for the implementer:** the trade-off here is real and is yours to make.
Withholding less means lower latency and a wider window for a leak if the candidate
detector is wrong; withholding more is safe but keeps the lag. The detector must be
_conservative_ — when unsure, withhold. See the "Your call" section at the end of this
plan.

**Verification:** `pytest tests/test_turn_prose.py -q` green including all pre-existing
leak cases; harness shows the emitter's lag drop from 34 chars to ~0 on prose that
contains no boundary-like tail.

---

## Task 4 — Settle the reply when the prose ends, not when the run ends

**The largest perceived win, and it costs nothing.** Today `Completed` is written only
after `format_with_retry` has made a second (and on rejection, a third) LLM call and
the session has been persisted. Throughout that window the caret blinks and the
composer is disabled (`CoachPage.tsx:268`), so the user believes the model is still
writing text that has in fact been finished for seconds.

This is safe because the visible text does not change afterwards: every turn service
overwrites `validated.coach_turn.text` with the streamed `prose` whenever `prose` is
non-empty (`profile_coach.py:234`, and the same pattern in `mock_interview.py` /
`scout.py`). The formatter's contribution is structure, not prose.

- [ ] Add a `Settled` event to `sessions/stream.py` (`tag = "settled"`, empty payload). **Do not** add it to `TERMINAL_TAGS`.
- [ ] Emit it from `persona_output` immediately after `emitter.finish()`, guarded on `prose` being non-empty — when nothing streamed (`stream_enabled` off, or a non-streaming agent) the reply genuinely does arrive from the formatter and must keep the caret.
- [ ] Mirror the tag in `web/src/lib/chat/events.ts` (`STREAM_EVENT_TAGS`, `StreamEvent`, `parseStreamEvent`) and add a `"settled"` status to `useChatStream`: the EventSource **stays open** (a `notice` and the terminal still follow), but `status` leaves `"streaming"`.
- [ ] Update `CoachPage`, `InterviewPage`, and `ScoutPage`: `busy` stops including `stream.status === "settled"`, and `ChatMessage`'s `streaming` prop (which drives the caret) goes false. The run may still be `"running"` — show a quiet secondary indicator ("saving…") rather than a blocked composer, so a user who wants to type their next message can.

  **Implementation correction (2026-08-02):** keep submission blocked until the
  current run is terminal. Each route uses `singleton_conflict="raise"`, and the
  session is not persisted until formatter work completes, so launching on
  `settled` would race stale state and return a busy conflict. `settled` enables
  typing and removes the caret/stop affordance while a quiet saving state keeps
  Send disabled until persistence completes.

- [ ] Update the Python↔TS tag parity test so a missing mirror fails CI.

**Risks:** the degraded path (`_degraded_turn`, and the `TurnRejected` fallback) also
renders `prose`, so text still doesn't change — but confirm this per service before
settling in that service. If a service can replace visible text post-format, it does
not get `Settled` until that is fixed.

**Verification:** an end-to-end API test asserting event order `text… → settled →
[notice] → completed`, and that `settled` is never the last event of a successful run;
web tests asserting the caret clears and the composer re-enables on `settled` while
the EventSource is still open.

---

## Task 5 — Stop paying an open/close per log row

Small, free, and it also reduces contention with the reader on Windows.

- [ ] `RunStreamSink` opens its handle once (lazily, on first append) and holds it until `close()`, writing + `flush()` per row. `flush()` stays — `StreamTail` relies on complete newlines being visible to a separate reader.
- [ ] `close()` must close the handle on every path, including the exception paths in `with_conversation_stream`.
- [ ] Confirm `StreamTail` still reads correctly from a file with a live open append handle (it opens `"rb"` independently — verify on Windows specifically, where sharing semantics differ from POSIX).

**Verification:** `pytest tests/test_sessions_stream.py -q` green; add a test that a
sink whose `work` raises still leaves no open handle (assert the file can be deleted).

---

## Task 6 — Make browser cost per delta O(new text), not O(transcript)

Today one SSE event re-renders every message in the thread and re-runs `ReactMarkdown`
over each one's full text. With a 20-message coaching session that is 20 full markdown
parses, four times a second.

- [ ] Wrap `ChatMessage` in `React.memo`. Durable messages come from query data with
      stable identity, so only the streaming message re-renders.
- [ ] Split `TextPart` into block-level chunks: partition on the last `\n\n` into
      _settled_ text (complete blocks, will not change) and a _live tail_. Render settled
      blocks through a `memo`'d `<MarkdownBlock text>` keyed by block index, and the tail
      through a non-memoised one. A delta then re-parses one paragraph.
- [ ] Move the auto-scroll effect's `scrollHeight` read into `requestAnimationFrame` so
      it stops forcing synchronous layout inside React's commit phase.
- [ ] `ReasoningPart` renders plain text inside a **collapsed** `Collapsible`. Confirm
      the content is not mounted while collapsed; if it is, gate it on open state — a
      reasoning model streams thousands of characters nobody is looking at.

**Verification:** the Task 1 render-count harness shows `TextPart` renders per event
constant in transcript length; existing `ChatThread.test.tsx` / `CoachPage.test.tsx`
stay green; markdown output is byte-identical across the settled/tail split (a table or
list must not break when its blocks are parsed separately — **test this explicitly**,
it is the one real risk in this task).

**Implementation correction (2026-08-02):** do not split Markdown at blank lines.
CommonMark constructs including lists, block quotes, fenced code, and setext headings
can cross that seam, so the proposed split cannot preserve output. Memoising durable
`ChatMessage`s removes the O(transcript) work while each changing message keeps one
semantically correct Markdown parse. A true incremental Markdown renderer is separate
work and needs an AST-aware design.

---

## Task 7 — Stop paying a token round trip on every turn

`useChatStream` requests a fresh `link-token` before opening the EventSource whenever
there is no static bearer — which is every turn in cookie-authenticated multi-user mode.

- [ ] Cache the SSE link token in a module-scoped ref with its expiry; reuse it until it
      is near expiry or the connection is rejected, then re-mint once.
- [ ] A native browser `EventSource` error does not expose the HTTP status. When the
      first connection using a cached SSE token fails, invalidate the cache, re-mint,
      and retry exactly once before returning to normal reconnect handling. This may
      re-mint after a network failure too, but preserves the intended expired-token
      recovery without relying on unavailable status data.
- [ ] Keep the token purpose-bound to SSE (ADR-0003: query tokens are never general API
      authorisation). Caching changes _when_ it is minted, never _what it authorises_.

**Verification:** a web test asserting two consecutive turns issue one `link-token`
call; a test asserting a rejected stream re-mints and reconnects.

---

## Task 8 — Cache the persona agents' stable prefix

`discovery/scout.py:301` and `tailor/agents.py:195` already pass
`cache_system_prompt=capabilities.supports_prompt_cache`. `build_coach_agent`
(`profile/coach.py:438`), the interviewer (`interview/agent.py:354`), and the formatters
do not — so the longest-lived prompts in the product re-pay full input cost and full
prefill latency on every turn.

- [ ] Pass `cache_system_prompt=capabilities.supports_prompt_cache` to the coach,
      interviewer, and formatter builders, matching the existing call sites exactly.
- [ ] Audit prompt _ordering_ for cache-prefix stability. `run_message_turn` composes
      `overview → agenda → transcript → user message`. The agenda mutates when topics are
      added, which invalidates the cache for the (append-only, much larger) transcript
      behind it. Reorder to **stable → append-only → volatile**: `overview → transcript →
    agenda → user message`.
- [ ] Consider moving `_overview(root, engine)` — stable for a whole session — into the
      cached system prompt rather than the user turn. **Verify first** whether agno's
      `cache_system_prompt` covers only the system block; if user-message cache
      breakpoints are not exposed, record that as a limitation in `CLAUDE.md` rather than
      guessing at an API.
- [ ] Measure with `scripts/stream_latency.py` on turn 1 vs turn 6 of a session. If TTFT
      does not improve, revert — an unverified caching flag is noise.

**Verification:** offline tests assert the flag reaches the builder and that prompt
section order is as specified; live probe shows TTFT improvement on later turns, or the
task is reverted.

---

## Task 9 — Retune the sink batch window against real numbers

Deliberately last: `flush_interval=0.08` / `flush_chars=240` were chosen when a 250 ms
poll sat downstream and the browser re-parsed the world per event. Once Tasks 2 and 6
land, both constraints are gone and the right values may be smaller.

- [ ] Re-run the Task 1 harness at (0.08, 240) — the current values — and at (0.04, 120)
      and (0.02, 60). Record events/turn, log bytes/turn, and render count/turn for each.
- [ ] Pick the smallest interval whose event count stays within ~2× today's and whose
      render cost is flat. **Record the chosen numbers and the measurement that chose
      them** in the docstring, replacing the current DeepSeek-era rationale.
- [ ] Keep reasoning and text on separate budgets — that rule is load-bearing (a kind
      change flushing the other is what stopped the per-token alternation bug) and is not
      up for retuning.

**Verification:** event count per turn does not regress toward the pre-batching 1,846;
the docstring cites the new measurement.

---

## Task 10 — Documentation and regression guards

- [ ] Update `CLAUDE.md`'s streaming section: the transport is now notify-with-poll-fallback;
      `settled` separates reply-complete from run-complete; the holdback is candidate-based;
      the sink's batch constants cite Task 9's measurement.
- [ ] Add an ADR **only if** Task 2 or 4 provoked a design decision worth pinning (e.g.
      "the NDJSON log stays the durability mechanism and never becomes the transport").
- [ ] Add the perf harness to the `dev` CI job if it runs in under a few seconds; otherwise
      leave it to `main`'s full gate.
- [ ] Fill the **Measured baseline** table's after-column and paste the before/after into
      the PR description.

---

## Expected result

|                                   | Before (derived)                      | After (target)            |
| --------------------------------- | ------------------------------------- | ------------------------- |
| Added transport latency per chunk | ~205 ms mean / 330 ms worst           | < 20 ms                   |
| Lag behind model cursor           | 34 chars (~8 tokens)                  | ~0 on boundary-free prose |
| Caret stops blinking              | after formatter call (+retry)         | at end of prose           |
| Browser cost per delta            | O(whole transcript)                   | O(one paragraph)          |
| Round trips before first byte     | POST turn + POST link-token + connect | POST turn + connect       |

---

## Your call — the one decision I've deliberately left open

**Task 3's `_safe_prefix_len`.** I've prepared the seam (`ProseEmitter.feed` in
`src/resume_agent/sessions/turns.py:92`, replacing the `safe_length = len(self.\_pending)

- self.\_holdback` branch), but the policy itself is a genuine security/latency trade-off
  that belongs to whoever owns the leak risk, not to a default:

- **Aggressive** — withhold only from the last `\n\n`, or from a trailing run of
  `-\*\_\`` characters. Lowest latency; correctness rests entirely on that character set
  being an exhaustive list of what a boundary can start with.
- **Conservative** — withhold from the last `\n\n` _or_ the last `MARKER_MAX_LEN`
  characters, whichever is earlier. Still flushes fully on prose that has no blank-line
  tail (the common case, so most of the win), but keeps a fixed safety margin for the
  emphasis-wrapped sentinel shapes `_MARKER` tolerates.

The failure modes are asymmetric: too aggressive leaks a `draft:` or `PROPOSE |` line
into the chat window; too cautious just keeps some lag. I'd take **conservative** — the
common-case win is nearly the same and the boundary regex has already been widened twice
in response to real model behaviour (DeepSeek's bare `---` rules, the Scout's proposal
table). Which do you want, and is there a boundary shape you already know a model emits
that neither branch covers?
