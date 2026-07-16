# 6. Turn-per-run conversational sessions on durable workspace files

Date: 2026-07-15

## Status

Accepted

## Context

The Profile Coach replaces the batch Profile Interview with a real
conversation: one question per exchange, the coach reacting to each answer,
topics closing in approval-gated draft notes. A conversation needs state
between exchanges — something no existing feature has. Three architectures
were considered:

1. **Turn-per-run over durable session files** — each user message triggers
   one short background Run through the existing RunManager; the entire
   conversation (transcript, agenda, drafts, recap, impact) lives in a
   per-session JSON file in the workspace (`data/profile/coach/`), mutated
   only by delta-under-lock writes. The client watches the run via SSE and
   re-fetches the session on completion.
2. **Long-lived agno session agent** — a live `Agent` with agno session
   memory held in server memory per conversation. Chat-natural, but state
   dies on restart or redeploy (Railway restarts mid-session would drop
   conversations), it cannot be faked offline the way the suite fakes every
   agent (single `run()` calls through the Runner seam), and it creates
   per-process affinity that fights multi-user tenancy.
3. **WebSocket streaming chat** — token-streaming transport for the real
   "typing" feel. Best perceived latency, but introduces a transport the
   codebase does not have (everything is REST + SSE), and it still requires
   architecture 1's durable state underneath to survive restarts.

## Decision

Conversational features run as **discrete turn-runs over durable per-session
workspace files**. Each turn is one bounded agent invocation (ADR 0005
tool-loop rules apply) submitted through RunManager with a per-user singleton
key; the session file is the single source of truth, written atomically and
mutated only by re-loading under the process lock and applying a delta. A
run that fails leaves the session exactly as it found it — including "not
existing yet": the opening turn materializes the session file, so a failed
start leaves no residue.

## Consequences

- Sessions survive server restarts and redeploys; the only thing lost with a
  process is the in-flight turn, and retry is resending the same message.
- Offline testing stays uniform: turn agents are faked like every other
  agent; a scripted conversation is a sequence of canned turns against a
  temp-dir session file.
- Coach replies appear whole after a few seconds of run latency — no token
  streaming. Accepted: coaching quality lives in the content, not the
  typing effect.
- The client's chat loop is poll-shaped (submit → watch run → re-fetch
  session), reusing the existing SSE run tracker with zero new transport.
- Concurrent mutations (a note approval landing while a turn runs) are safe
  by the delta-under-lock discipline, not by request serialization.
- Adopting token streaming later means layering a transport over this state
  model, not replacing it; adopting in-memory agents would be a reversal of
  this decision and must revisit restart-safety, tenancy affinity, and the
  offline test strategy.
