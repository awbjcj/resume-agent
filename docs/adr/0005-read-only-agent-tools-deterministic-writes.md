# 5. Read-only agent tools, deterministic writes

Date: 2026-07-14

## Status

Accepted

## Context

Source Scout and the Profile Interview introduce the codebase's first
tool-calling agent loops. A tool-equipped agent could, in principle, mutate
state directly — call `add_source` when it finds a board, write note sources
as it interviews, trigger builds. Three architectures were considered:

1. **Plan-then-execute** — single-shot structured-output agents (the existing
   pattern), no tools. Predictable, but discovery cannot self-correct: a
   guessed Greenhouse token that 404s ends the attempt.
2. **Full read-write loop** — agents call mutating tools directly. Maximally
   autonomous, but writes happen inside an unpredictable loop: hard to bound
   cost, hard to test offline (the suite fakes every agent), and an agent
   misfire mutates `connectors.yaml` or the profile corpus with no approval
   step.
3. **Read-only tools + deterministic writes** — agents run real tool loops,
   but every tool only reads, searches, probes, or verifies. The loop ends in
   structured output; all mutations run afterwards through existing services
   (`add_source`, `add_note_source`, profile build), gated by user approval.

Two invariants weigh heavily. Fact-lock requires that nothing an LLM produces
becomes a fact without a literal source behind it. Source priority and the
connectors.yaml format assume writes go through one validated path
(`preview_source` → `add_source`).

## Decision

Every agent tool loop in this codebase exposes only read-only tools. The
agent's final answer is structured output. All writes happen after the loop,
through existing deterministic services, behind explicit user approval.
Anything the agent claims to have verified via a tool is re-verified
deterministically before being presented as validated — the tool exists so the
agent can self-correct, not so the system can trust its memory.

This applies to Source Scout (`check_source` probes but never adds),
the Profile Interview (corpus readers; answers become notes only on submit),
and any future tool-loop agent.

## Consequences

- Offline testing stays uniform: tool-loop agents are faked exactly like
  single-shot agents (canned structured output); tools need no network in
  tests because no test exercises a real loop.
- Cost stays bounded by construction: loop caps (`tool_call_limit`, search
  `max_uses`) plus a deterministic post-phase, rather than an open-ended
  read-write session.
- Fact-lock and source-priority invariants hold without new enforcement:
  the write paths that guard them remain the only write paths.
- The price is a double fetch: probes inside the loop are repeated by the
  deterministic re-validation pass. Accepted — validation is the cheap step,
  and the duplication is what makes the agent's output untrusted-by-default.
- Giving a future agent write tools is an explicit reversal of this decision
  and requires revisiting the offline test strategy, budget enforcement, and
  approval UX that assume it.

## Amendment (2026-07-15)

The Profile Coach (successor to the batch Profile Interview; see ADR 0006 for
its conversation architecture) is the second tool-loop instance under this
rule. Its approval write is the draft-note save, and it adds a mechanical
guard in this decision's spirit: coach-proposed verbatim quotes are validated
against the session transcript before a draft is ever shown, so the agent
cannot fabricate the user's words.
