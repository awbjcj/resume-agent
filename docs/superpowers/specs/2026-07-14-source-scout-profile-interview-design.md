# Source Scout + Profile Interview — Design

Date: 2026-07-14
Status: Approved

## Correctness clarifications (2026-07-14 implementation audit)

- Candidate validation returns structured failure codes. A reachable page with
  no supported ATS is `unverified`; an unreachable page is `failed`. UI logic
  never classifies by matching human-readable error text.
- Source Scout dedupes normalized URL/token identities against both configured
  sources and earlier rows in the same report while preserving proposal order.
- The discovery result carries browser/scrape capability so an unverified row is
  disabled before approval when scrape is unavailable.
- Public scrape additions reject unsafe URL shapes at the API/service boundary.
- Both two-stage workflows preflight every configured model provider they will
  call, and every tool returns a bounded error value rather than leaking an
  exception into the model loop.
- Interview rounds have an explicit submitted timestamp. Even a round whose
  answers are all skipped is one-shot, and answer creation/history mutation are
  serialized per profile.
- Interview answer intake requires an existing literal primary corpus source;
  an interview note can never accidentally become the primary resume.
- The history API resolves recorded note IDs to actual answer text for display
  while the sidecar continues to store only document IDs. Missing note files
  remain visible as unavailable replies rather than erasing history.
- Application code assigns unique question IDs and enforces the item cap across
  questions plus research actions; it does not trust formatter IDs or counts.
- The CLI follows the same default as the API: answers trigger a build unless
  `--no-build` is selected.
- Frontend run tracking uses the repository's `RunRecord.status` contract, and
  research-action controls call the existing GitHub-sync and URL-intake paths.

Two features built on one new foundation — the repo's first **tool-calling agent
loops**, constrained by a single rule: **agents get read-only tools; every write
goes through an existing deterministic service after structured output and user
approval.**

- **Part A — Source Scout:** a free-text prompt ("I'm interested in Anthropic
  and AI infra startups") becomes a validated, user-approved set of new job
  sources in `connectors.yaml`.
- **Part B — Profile Interview:** a gap-driven, round-based interview agent
  that inspects the profile corpus, asks targeted questions, and suggests
  research actions; answers become note sources that flow through the normal
  extract pipeline.

Parts A and B are independently shippable. Each gets its own implementation
plan; A has no dependency on B.

---

## Architecture rule (applies to both parts)

Agents run real agno tool-calling loops, but:

1. Every tool exposed to an agent is **read-only** (search, fetch, verify,
   inspect). No tool mutates `connectors.yaml`, the corpus, facts, or the DB.
2. The agent's final answer is **structured output** (a Pydantic schema).
3. All mutations happen after the run, through **existing services**
   (`add_source`, `add_note_source`, `add_url_source`, profile build), gated by
   explicit user approval in the UI/CLI.
4. Anything the agent claims to have verified is **re-verified
   deterministically** before it is shown as validated.

This mirrors `profile/synthesis.py`'s generate → verify → bounded-repair
pattern and keeps fact-lock and config writes on deterministic, tested paths.
Recorded as ADR 0005 (read-only agent tools, deterministic writes).

---

## Part A — Source Scout

### Flow

`POST /api/sources/discover` `{ prompt }` → `202` with a Run (new kind
`source-discovery`), executed by `RunManager` like pull/tailor. CLI:
`resume-agent scout "<prompt>" [--add]` (a `sources discover` subcommand would
collide with the existing `sources` command in typer).

The worker has three phases, streamed over the existing run SSE:

**1. Context assembly (deterministic).** Build the agent's grounding:

- Compact profile summary: recent titles from facts, top skill-matrix tokens.
- `search.yaml` summary: role anchors, locations.
- Existing sources: every configured token/board URL, so the agent never
  proposes a duplicate.

Profile/search files may be absent (fresh workspace); the scout runs with
whatever context exists — prompt-only in the worst case.

**2. Agent loop.** `build_source_scout_agent()`:

- Model + web search from the existing `build_search_equipped(mid_tier)`
  (Anthropic native / OpenAI native / DuckDuckGo tool fallback).
- One custom read-only tool: `check_source(url)` — wraps `preview_source()`
  and returns `{ ok, ats, token, role_count, error }`. Writes nothing. Probes
  run with a small fetch limit (loop speed) and always with the browser
  disabled, so no probe can pop a visible browser mid-loop; browser-only
  sources (Tesla) surface their degradation reason instead.
- The agent finds the named companies' career boards, expands the prompt into
  similar companies (using the profile/search grounding for relevance), probes
  candidate URLs with `check_source`, and self-corrects on misses (e.g. a
  guessed Greenhouse token 404s → search again, try Lever).
- Bounded: agno `tool_call_limit`, search `max_uses`, and a module constant
  `MAX_CANDIDATES = 12`.
- Structured output: `ScoutReport { candidates: list[ScoutCandidate] }` where
  `ScoutCandidate = { company, careers_url, reason, confidence }`.

**3. Deterministic re-validation.** Candidates are deduped against existing
sources (token/URL), then every survivor runs through `preview_source()` again
— concurrently via `gather_isolated` + `asyncio.to_thread` (it is sync httpx)
— with per-candidate progress ("validating 4/12"). The agent's claims are
never trusted for the final verdict. Failures never abort the run (same
isolation philosophy as `companies.py`).

The run result payload carries the full candidate table: validated rows
(`ats`, `token`, resolved URL, live `role_count`), **unverified rows**
(careers URL found but no supported ATS detected — see below), and failed
rows (reason). A validated row with `role_count = 0` stays selectable: a
source is durable and openings change; the UI hints at the empty count.

**Unverified rows (no supported ATS).** A company whose careers page fails
`detect_ats` is offered as a **scrape target**: a new explicit
`provider="scrape"` branch in `add_source` writes `config.scrape.targets`
(Source Manager can already toggle/limit/remove scrape targets, just not add
them). These rows are explicitly marked unverified — a recipe is learned on
first pull, so "validated to exist" applies only to ATS-backed rows. The
action is disabled with an explanatory tooltip when `browser_enabled=false`
(Railway), matching the browser-degradation doctrine.

### Approval

The Sources page renders the table with checkboxes; validated rows are
selectable, unverified rows carry the "add as scrape target" action, failed
rows are greyed out with their reason. "Add selected" calls the **existing**
`POST /api/sources` per row (`add_source` re-validates once more and writes
`connectors.yaml`). Scrape adds ride the same endpoint via a new explicit
`provider="scrape"` branch in `add_source` (skips ATS detection, writes
`config.scrape.targets`) — so still no new mutation endpoint. Per-row add
failures surface inline; other rows proceed.

CLI `--add` adds all validated candidates through the same service call.

A CLI `scout --add` run never adds unverified rows — scrape targets remain an
explicit per-row web choice (or a manual `provider="scrape"` add).

### Failure handling

- No provider key / `search_mode=off` → 4xx `ApiException` before the run
  starts (scout requires web search).
- Agent/LLM failure → run fails with the standard error envelope.
- Zero candidates or zero validated candidates → successful run with an empty
  table and a summary message, not an error.

---

## Part B — Profile Interview

### Flow

`POST /api/profile/interview` → `202` with a Run (new kind
`profile-interview`). CLI: `resume-agent profile interview` (one round in the
terminal: print questions, read answers, save notes, trigger build).

**1. Context assembly (deterministic).**

- Facts summary: experiences/projects with bullet and metric counts.
- Skill-matrix stats: rows with thin evidence.
- Corpus manifest: document names, types, origins, sizes.
- **Market gaps:** a compact Match/Gap summary — top demanded canonical
  tokens (from the existing cluster map) with weak or missing profile
  evidence — so questions target what the user's discovered jobs actually
  ask for. Degrades gracefully to corpus-only when no jobs exist yet.
- **History:** previously asked questions from
  `data/profile/interview_history.json` (per-workspace sidecar), injected so
  rounds never repeat. Kept outside the corpus so it never pollutes
  extraction. The history also records each answer's resulting note-doc id,
  making it the single source the conversation view reconstructs from.

**2. Agent loop.** `build_interview_agent()` with read-only tools:

- `list_corpus_documents()` — manifest rows.
- `read_document(doc_id)` — content, truncated to a size cap.
- `list_github_sources()` — harvested repos and their doc sizes.

The agent inspects documents where the summary looks thin before formulating
anything.

**3. Structured output — one round.** Up to `MAX_QUESTIONS = 8` items, each
either:

- a **question**: `{ id, gap, why_it_matters, question_text, related_ref }`
  (`related_ref` = fact or doc id), or
- a **research action**: `{ kind: "harvest_repo" | "request_url", target,
  why }` ("research suggestion" is avoided — a Suggestion belongs to the
  match-gap advisor).

Questions must demand **evidence**, never yes/no claims: "where did you use
Terraform and what did you do with it," not "do you know Terraform?" —
market-gap questions especially must not invite thin assertions.

The round is the run's result; asked questions are appended to the history
file.

### Answering

The round renders **chat-styled**: the agent's questions appear as message
bubbles in a conversation column, the user's answers as replies, research
actions as inline action chips ("Re-harvest repo" → existing GitHub sync,
"Provide URL" → existing URL intake) — visual patterns borrowed from agno's
agent-ui. The semantics stay round-based: answers are skippable, and one send
submits the whole round. Past rounds render above the current one,
reconstructed from the interview history — there is no chat session state.

`POST /api/profile/interview/{run_id}/answers` `{ answers: [{ question_id,
text }], build: bool = true }`:

1. Each non-empty answer becomes a note source via the existing
   `add_note_source` (title `Interview — <gap>`); the note-doc id is recorded
   in the history file.
2. A profile-build run is started (existing build path) and its run id
   returned alongside the created documents — unless `build=false` (a "save
   only" option for users batching evidence) or a build/reset is already
   active, in which case notes still save and the response says
   `buildStarted=false` with the reason.
3. A second submission for the same `run_id` is refused with `409` — one
   round, one submission.

Fact-lock is untouched: answers are user-authored literal corpus documents
flowing through the normal extract pipeline. The agent never writes facts.

### Iteration

After the rebuild the user can start another round; the agent sees the new
notes plus the history file, so successive rounds converge on remaining gaps.

---

## Cross-cutting foundation

- **Seams intact.** Models via `build_model` / `build_search_equipped`; agents
  wrapped in `AgentRunner` (retry + `record_call` usage recording works
  unchanged for tool loops). A small shared helper in `llm_runner.py` sets
  agno tool-loop bounds (`tool_call_limit`) in one place.
- **Tools live next to their builders** (`discovery/source_scout.py`,
  `profile/interview.py`) as plain agno `@tool` functions over captured
  workspace paths — never request state; they run on `RunManager` worker
  threads with their own DB sessions.
- **Model tier:** `mid` for both agents. Caps are module constants
  (`MAX_CANDIDATES`, `MAX_QUESTIONS`, tool-call limit); promotable to Settings
  later.
- **API/contracts:** two new run kinds, three new endpoints
  (`POST /api/sources/discover`, `POST /api/profile/interview`,
  `POST /api/profile/interview/{run_id}/answers`), new CamelModel schemas;
  regenerate `contracts/openapi.json` + TS client; drift gate updated.
- **Tenancy:** `RunManager.submit` already copies `UserContext`; history and
  artifacts live under the workspace data root; shared-key budgets enforced
  via the existing `record_call` path.

## Testing (offline, like everything else)

- Both agents are faked with canned structured outputs; `preview_source` faked
  per URL; no network.
- Part A: dedupe against existing sources, validation fan-out and isolation,
  run lifecycle, empty-result run, key/search-mode preflight, the
  `provider="scrape"` add branch (including its `browser_enabled=false`
  refusal), contract gate.
- Part B: context assembly (thin-doc and market-gap inputs, graceful
  no-jobs degradation), history-based no-repeat injection, answers → note
  sources → build trigger, busy-build `buildStarted=false` branch, duplicate
  submission 409, skipped questions produce no documents, contract gate.

## Non-goals

- No persistent chat session or streamed turns — the conversation UI is a
  chat-styled *presentation* of stateless rounds reconstructed from the
  interview history.
- No open web search about the user in Part B (repo + user-URL evidence only).
- No agent-side writes of any kind; no new mutation endpoints beyond the
  interview answers submission.
- No changes to fact-lock, source-priority, or dedup invariants.
