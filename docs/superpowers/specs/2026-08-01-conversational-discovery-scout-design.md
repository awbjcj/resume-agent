# Conversational Discovery Scout

**Date:** 2026-08-01
**Status:** Approved, pending implementation plan
**Scope:** `discovery/scout.py` (new), `discovery/scout_store.py` (new),
`services/scout.py` (new), `services/scout_context.py` (new),
`api/routers/scout.py` (new), `api/schemas/scout.py` (new), `cli.py`,
`web/src/features/scout/` (new); retires `discovery/source_scout.py`,
`discovery/search_scout.py`, `services/source_discovery.py`,
`services/search_discovery.py`, `web/src/features/sources/DiscoverCompaniesDialog.tsx`,
`web/src/features/search-scout/`

**Sequencing:** This is spec 2 of 2. Spec 1
(`2026-08-01-streaming-conversational-turns-design.md`) built the streaming
substrate this document consumes: `AgentRunner.stream()`, `sessions/stream.py`,
`sessions/turns.py`, the generic `SessionStore`, `GET /api/runs/{id}/stream`,
and `web/src/components/chat/`. Nothing in that substrate changes here.

---

## Problem

Company-source discovery and search-term suggestion are both one-shot. The user
writes one prompt, a run executes research → format → validate, and a table
appears. There is no way to say "these are all too big, find seed-stage ones" or
"drop the exclude terms, keep the titles" without discarding the result and
re-prompting from zero — which loses the agent's accumulated reasoning, re-pays
for the web searches, and re-proposes everything the user just rejected.

Three concrete costs:

1. **No refinement.** The prompt is fire-and-forget. Correcting the agent means
   starting over.
2. **No feedback signal.** The agent is told what sources already exist
   (`EXISTING SOURCES`) but never what the user *rejected*, so a second run
   re-proposes the same companies.
3. **No visible progress.** The research agent's web searches and `check_source`
   probes run inside a blocking call behind a spinner, even though they are
   exactly the work the user would want to watch.

A fourth cost is duplication. `source_scout.py`/`search_scout.py` and
`source_discovery.py`/`search_discovery.py` are near-identical pairs — the same
research/format agent structure, the same context assembly, the same
dedupe-and-rank pass — differing only in what they propose. Two of everything
means every fix lands twice.

## Non-goals

- Letting the Scout write configuration. Every mutation stays a deterministic
  endpoint a human triggers. See "The write boundary".
- Grounding proposals in pull telemetry ("which sources actually produced good
  jobs"). Tempting and out of scope.
- Cross-process locking for `search.yaml`. See "Known bounds".
- Changing the streaming substrate, the SSE transport, or the chat primitives.
- Editing or branching turns. ADR-0006 sessions are append-only.

---

## Architecture

### Module layout

| New                        | Purpose                                                              |
| -------------------------- | -------------------------------------------------------------------- |
| `discovery/scout.py`       | Persona + formatter agents, `ScoutTurn` schema, `normalize_turn`     |
| `discovery/scout_store.py` | `ScoutSession`/`ScoutProposal`/`ScoutTurnRecord` on `SessionStore`   |
| `services/scout_context.py`| Grounding blocks, canonicalization, dedupe keys                      |
| `services/scout.py`        | Turn service, approval, dismissal, session views                     |
| `api/routers/scout.py`     | Endpoints                                                            |
| `web/src/features/scout/`  | Page, hook, `ProposalRail`, `ProposalCard`                           |

**Consolidated, not duplicated.** `source_scout.py` and `search_scout.py`
collapse into one `discovery/scout.py`: a single persona with two proposal
types, whose instruction body is the merge of the two existing research
instruction lists. `source_discovery.py` and `search_discovery.py` lose their
`run_*` orchestrators, and their genuinely reusable halves — `scout_context`,
`_canonical_url`, `_candidate_keys`, `_existing_keys`, `_existing_terms`,
`_EXISTING_FIELD` — move into `services/scout_context.py`.
`discovery/scout_models.py` (`Citation`, `is_http_url`, `citation_rows`) is
unchanged and shared.

### Session model

```python
class SourcePayload(ExtensibleModel):       # kind == "source"
    company: str = ""
    url: str = ""
    ats: str | None = None
    token: str | None = None
    role_count: int | None = None
    error_code: str | None = None

class TermPayload(ExtensibleModel):         # kind == "search_term"
    value: str = ""
    term_kind: SuggestionKind = "keyword"   # keyword|title|role_anchor|
                                            # exclude_term|location|seniority|adjacent_role
    # SuggestionKind, the seniority vocabulary, and its validator move from
    # search_scout.py into discovery/scout.py unchanged.

class ScoutProposal(ExtensibleModel):
    id: str = ""                            # "p1"; stable within the session
    kind: Literal["source", "search_term"] = "source"
    source: SourcePayload | None = None     # exactly one payload is set,
    term: TermPayload | None = None         #   enforced by a model_validator
    reason: str = ""
    fit_score: int | None = None            # 0-100
    citations: list[Citation] = []
    check: Literal[
        "validated", "unverified", "failed", "duplicate", "avoid", "new"
    ] = "new"
    check_error: str = ""
    status: Literal["pending", "added", "dismissed"] = "pending"
    dismiss_reason: str = ""
    resolved_at: str | None = None

class ScoutTurnRecord(ExtensibleModel):
    role: Literal["scout", "user"] = "user"
    kind: Literal["reply", "recap", ""] = ""
    text: str = ""
    at: str = ""
    notice: str = ""
    proposal_ids: list[str] = []            # proposals this turn attached

class ScoutSession(SessionModel):
    goal: str = ""                          # standing brief; refinable mid-session
    turns: list[ScoutTurnRecord] = []
    proposals: list[ScoutProposal] = []
    recap: str | None = None
    ended_at: str | None = None
```

Sessions are durable JSON at `<workspace>/scout/session-<id>.json`, resolved the
way `get_interview_dir` resolves `root / "interview"`, and carry the full
`SessionStore` lifecycle: process-wide mutation lock, atomic validated write,
listing with the archived filter, archive/unarchive/delete.

`ScoutProposal` uses a `kind` discriminator with exactly one payload set rather
than a flat union of all fields, so a source row cannot silently carry a
`term_kind` and the formatter cannot half-fill a proposal. A `model_validator`
rejects zero or two payloads.

### One structural difference from the Coach

The Coach opens *itself*: it reads the profile and proposes a bounded agenda of
topics, and `POST /profile/coach/sessions` takes no body. The Scout is
user-driven, so there is **no agent-authored opening turn and no topic agenda**.
`POST /api/scout/sessions` carries the user's first message; it is stored as
`goal` and answered in the same run.

`goal` replaces `topics` as the standing context re-read each turn. The user can
amend it in prose ("also include Toronto"), which the formatter surfaces as a
`goal_update` field the normalizer applies to the session. Topic-status
machinery (`open`/`drafted`/`saved`/`skipped`) has no Scout analogue and is not
ported.

**One active session at a time**, as with the Coach: `POST /api/scout/sessions`
returns `409 SESSION_ACTIVE` when an unended session exists. Ending a session
streams a recap turn (`ScoutTurnRecord.kind == "recap"`) summarizing what was
added, what was dismissed, and what remains pending, then sets `status="ended"`.

**Ending a session does not freeze its proposals.** `approve` and `dismiss` gate
on the *proposal's* `status == "pending"`, never on the session's status, so a
user can still add a board from an ended session's rail — the same latitude
`approve_draft` gives a Coach note. Only new turns require an active session.

### The turn loop

Identical in shape to `services/profile_coach.py::run_message_turn`:

1. **Assemble the prompt** — `scout_context(...)` (profile recent titles, top
   skills, current search config, existing sources) + `render_goal(session)` +
   `render_ledger(session)` + `render_transcript(session)` + the untrusted user
   message.
2. **Stream the persona** — `persona_output(agent, prompt, sink, reporter,
   source="scout notes")` emits prose deltas up to `---METADATA---`, buffers the
   metadata tail, and forwards `ToolStarted`/`ToolCompleted` for every web search
   and `check_source` call. Each event is a cancellation checkpoint, so Stop
   works.
3. **Format and validate** — `format_with_retry(formatter, notes, ScoutTurn,
   normalize, label="SCOUT NOTES")`.
4. **Deterministic post-pass** — dedupe every proposal against existing
   configuration *and* against proposals already in this session; then a
   concurrent `preview_source` fan-out over fresh source proposals via
   `gather_isolated` with `on_complete=reporter.step` and
   `checkpoint=reporter.checkpoint`, exactly as `run_source_discovery` does
   today. Term proposals resolve to `new`/`duplicate` from `_existing_terms`.
   A proposal the agent marks `avoid` (today's negative signal: hiring freeze,
   layoffs, clear mismatch) skips the probe entirely and resolves to
   `check="avoid"` — it is evidence *against* a company, is never approvable,
   and may omit a careers URL provided it carries an evidence citation.
5. **Persist** — `apply_turn_delta` appends the user turn, the scout turn, and
   the proposals under the store lock, then the service returns the session view.

The turn's stored text is the **streamed prose, verbatim**, per spec 1's
message-source rule. Under `stream_enabled=false` the formatter's `message` is
authoritative again and everything else is unchanged.

### `render_ledger` is the feedback mechanism

Resolved proposals are rendered as deterministic evidence in every subsequent
prompt:

```
ALREADY ADDED: Modal (greenhouse), Baseten (ashby), keyword "inference serving"
DISMISSED — DO NOT PROPOSE AGAIN:
- Scale AI — user said: too big
- OpenAI — user said: already applied
```

Combined with the existing `EXISTING SOURCES` and current-search blocks, this is
the entire adaptation loop, and it is Python-rendered text — the agent is never
asked to remember what it proposed. Dismiss reasons are untrusted user text and
are rendered inside the same untrusted-data framing the rest of the context uses.

### Tools stay read-only

The persona agent's tool set is exactly:

- the provider's web search tools from `build_search_equipped(settings.mid_model, ...)`
- `check_source(url)` — the existing bounded probe, `preview_source(browser=False)`,
  which always returns JSON and never raises

Nothing else. `check_source` guides the agent's own research and renders as a
live tool chip — the visible-progress win. The **authoritative** status shown on
a proposal card comes from step 4's deterministic fan-out, never from the model's
assertion.

### Validation degradation

`format_with_retry` and spec 1's structural/integrity split are reused verbatim.
A new `ProposalRejected(TurnRejected)` is the analogue of `DraftRejected`:

| Class                   | Causes                                                                                    | Handling                                                                             |
| ----------------------- | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------- |
| **Structural**          | empty message, over-cap proposal count, malformed `goal_update`, unknown proposal `kind`   | Formatter retry; on second failure store the streamed prose with a notice             |
| **Proposal integrity**  | positive source row with no HTTP(S) URL, non-HTTP citation URL, out-of-vocabulary seniority, both/neither payload set | Formatter retry, then **drop the proposals, keep the turn**, attach a durable notice |

A bad proposal never destroys the Scout's reply. Notices are stored on
`ScoutTurnRecord.notice` so they survive a refresh.

### Caps

- **8 proposals per turn** — the rail stays readable and one turn cannot flood
  the ledger.
- **40 pending proposals per session** — bounds both the rail and the ledger
  block; the normalizer rejects a turn that would exceed it (structural class).
- **Transcript elision** — the interviewer's existing policy, so a 20-turn
  session does not grow the prompt without bound. The ledger renders recent
  resolutions plus a count of older ones.

---

## The write boundary

This is what "human approval" means structurally: the Scout has **no write
tool**. Every mutation is a deterministic endpoint triggered by a human action.

```
POST   /api/scout/sessions                              → 202 RunOut   { message }
POST   /api/scout/sessions/{id}/messages                → 202 RunOut   { message }
POST   /api/scout/sessions/{id}/proposals/{pid}/approve → 200 ScoutSessionOut
POST   /api/scout/sessions/{id}/proposals/{pid}/dismiss → 200 ScoutSessionOut  { reason? }
POST   /api/scout/sessions/{id}/end                     → 202 RunOut   (streamed recap)
GET    /api/scout/sessions                              → ScoutSessionsOut
GET    /api/scout/sessions/{id}                         → ScoutSessionOut
POST   /api/scout/sessions/{id}/archive | /unarchive    → ScoutSessionOut
DELETE /api/scout/sessions/{id}                         → 204
```

Turn routes go through the launch seam with `with_conversation_stream`, a
`scout` singleton key, and `meta={"stream": True, "sessionId": ...,
"turnCount": ...}` so refresh recovery selects the active run the same way the
Coach page does. Setup guards mirror `discover_sources_route`: missing model
keys → `SETUP_INCOMPLETE`, `search_mode == off` → `SEARCH_DISABLED`.

`approve` dispatches on `kind`:

- **`source`** → `add_source(provider="scrape" if check == "unverified" else
  "auto", url=..., label=company, country="com", connectors_path=...,
  search_path=...)` — the identical call today's `addSelected` makes.
- **`search_term`** → read-modify-write of `search.yaml` through `ConfigStore`,
  appending `value` to the field `_EXISTING_FIELD[term_kind]` names.

Approval refuses a proposal that is not `pending` with `409 CONFLICT`, mirroring
`set_draft_status`'s "draft already resolved". `dismiss` accepts an optional
reason capped at 200 characters.

### The `search.yaml` lost update, and how it is bounded

`ConfigStore.put` is a whole-document replace with no locking
(`services/config_store.py`): it validates, dumps, and `os.replace`s. Two
approvals in flight — or an approval racing a save from the Settings page — will
lose a term.

The term path therefore does `get → confirm still absent → append → put` inside
`scout_lock()` (the `SessionStore`'s process-wide `RLock`), and is **idempotent**:
approving a term already present marks the proposal `added` without a second
write. That bounds the race to a single process, which matches the rest of the
config layer and the single-service Railway deployment.

### Security

Proposal URLs originate from an LLM reading untrusted web pages, so both
`check_source` (during the turn) and `add_source` (at approval) continue to
resolve through `preview_source` and the ADR-0008 egress gateway. SSRF
validation, per-hop redirect revalidation, and size caps apply to an
agent-supplied URL exactly as to a pasted one. No new network sink is introduced
and no existing one is bypassed.

---

## Interface

Route `/scout`, reachable from the sidebar and from **"Ask the Scout"** buttons
on the Sources page and Search settings.

```
┌─ Discovery Scout ─────────────────┬──────────────┐
│ [transcript]                      │ PROPOSALS    │
│ You: AI infra startups, remote US │ ┌──────────┐ │
│ Scout: Let me search…             │ │ Modal    │ │
│  ⚙ web_search "AI infra hiring"   │ │ greenhse │ │
│  ⚙ check_source modal.com/careers │ │ 14 roles │ │
│ Scout: Found 6. Modal and Baseten │ │[Add][✕]  │ │
│ look strongest because…▌          │ └──────────┘ │
│ ┌───────────────────────────────┐ │ ┌──────────┐ │
│ │ Ask for a change…      [Send] │ │ │ keyword  │ │
│ └───────────────────────────────┘ │ │[Add][✕]  │ │
├───────────────────────────────────┴──────────────┤
│ SESSIONS  · today · Jul 28 · Jul 12   [archive]  │
└──────────────────────────────────────────────────┘
```

Every chat primitive is the one spec 1 built — `ChatThread`, `ChatMessage`,
`ChatComposer` (with `TranscribeButton`), the part components, and
`useChatStream(runId)` — reused unchanged. Reasoning parts are **shown**: unlike
the interviewer, the Scout has no in-character constraint to protect, and its
reasoning about company fit is useful to read.

`ProposalCard` carries the company or term value, the fit badge, the reason,
citation links, and `[Add]` / `[Dismiss]`. Its badge reads `status` first and
falls back to `check`, which keeps two distinct meanings apart that today's
dialog blurs:

| Badge                | Condition                                                    |
| -------------------- | ------------------------------------------------------------ |
| `Added`              | `status == "added"` — this session put it in your config     |
| `Dismissed`          | `status == "dismissed"`                                      |
| `14 roles`           | `check == "validated"` (falls back to `Validated` if no count) |
| `Scrape target`      | `check == "unverified"`                                      |
| `Already in sources` | `check == "duplicate"` — it was there before this session    |
| `Avoid` / `Failed` / `New` | the remaining `check` values                           |

`[Add]` is disabled for `avoid`, `failed`, `duplicate`, and any non-pending
proposal; scrape targets are additionally disabled with the existing explanation
when `browser_enabled` is false. Citation rendering is lifted from today's
dialog. "Add all validated" loops client-side with per-row error capture,
exactly as `addSelected` does now.

The streaming assistant bubble, stop, and in-place retry behave as spec 1
defines them; a stopped turn is discarded and the transcript is untouched.

---

## CLI

`resume-agent scout` opens a session and loops, driving the **same** service
functions with `ConsoleStreamSink`:

```
> AI infra startups hiring platform engineers, remote US
Scout: Searching…  ⚙ web_search  ⚙ check_source modal.com/careers
Scout: Found 6 boards. Modal and Baseten look strongest because…

  [1] Modal          greenhouse · 14 roles   fit 88
  [2] Baseten        ashby · 9 roles         fit 81
  [3] keyword        "inference serving"     new

> add 1 3
> skip 2 too early stage
> end
```

Commands: `add <n…>`, `skip <n> [reason]`, `end`, `quit`. Because it exercises
the identical turn, approval, and dismissal path with no browser and no HTTP
layer, a streaming or approval regression cannot hide in one client.

---

## Retirement

Deleted:

- `web/src/features/sources/DiscoverCompaniesDialog.tsx` (+ test),
  `web/src/features/sources/use-discover.ts`,
  `web/src/features/search-scout/` (dialog, test, hook)
- `POST /api/sources/discover`, `POST /api/search/discover` and their
  `DiscoverSourcesIn` / `DiscoverSearchIn` schemas
- `services/source_discovery.py::run_source_discovery`,
  `services/search_discovery.py::run_search_discovery` (the modules are absorbed
  into `services/scout_context.py`)
- `discovery/source_scout.py`, `discovery/search_scout.py` (absorbed into
  `discovery/scout.py`; `ScoutReport` and `SearchSuggestions` are replaced by
  `ScoutTurn`)
- CLI `scout` and `scout-search` commands (replaced by the conversational `scout`)

Agent-guidance keys migrate from `source-scout-research`, `source-scout-format`,
`search-scout-research`, `search-scout-format` to `discovery-scout` and
`discovery-scout-format`. `prompts/registry.py` projects the new builders.
Guidance lookup is already an allowlist, so stale keys in an existing
`agent_guidance.yaml` become inert and no migration script is required.

Contracts regenerate with `bash scripts/gen_ts_client.sh`;
`tests/api/test_openapi_contract.py` is the drift gate.

---

## Testing

The suite stays offline: no API key, no network, no browser.

- **Feedback loop.** Dismiss a proposal with a reason, run the next turn against
  a recording fake, and assert the prompt contains the company under
  `DISMISSED — DO NOT PROPOSE AGAIN` with the reason.
- **Write boundary.** Assert the built persona agent's tool names are exactly the
  search tools plus `check_source`. A regression that hands the agent a write
  tool fails here.
- **Approval.** Approving a `source` writes `connectors.yaml`; approving a
  `search_term` appends to the correct `search.yaml` field, preserves unrelated
  fields, and is idempotent; approving an already-resolved proposal returns 409.
- **Dedupe.** A proposal matching existing configuration, and the same proposal
  repeated in a later turn of one session, both resolve to `duplicate`.
- **Validation split.** A non-HTTP citation URL raises `ProposalRejected`: the
  proposals are dropped, the turn and its streamed prose are kept, and the notice
  survives a session reload.
- **Caps.** A turn proposing 9 rows, and a turn that would push pending past 40,
  are rejected structurally and degrade to prose plus notice.
- **Streaming.** `FakeStreamingRunner` scripted events: prose deltas, tool chips
  in arrival order, terminal `Completed`; `stream_enabled=false` reproduces the
  blocking path with the formatter's message.
- **Session lifecycle.** A second `POST /api/scout/sessions` while one is active
  returns `409 SESSION_ACTIVE`; after `end`, a new message returns `409` but
  approving a still-pending proposal succeeds. Refresh recovery selects the
  active run by kind plus session id; archive/unarchive/delete behave as the
  shared store defines.
- **Avoid rows.** An `avoid` proposal skips the probe, is rejected by `approve`,
  and is retained with its evidence citation even without a careers URL.
- **CLI.** `add`/`skip` drive the same service functions and mutate the session.
- **Retirement.** The removed routes are absent from `contracts/openapi.json`.

---

## Known bounds

- **Cross-process `search.yaml` writes are not serialized.** The idempotent
  read-modify-write under `scout_lock()` covers the single API process; a second
  process writing the same file concurrently can still lose a term. This matches
  the existing config layer and the single-service deployment, and is recorded
  here rather than assumed away.
- **A session's context grows with its length.** Elision and the ledger cap bound
  it, but a very long session is more expensive per turn than a short one.

## Risks

| Risk                                        | Mitigation                                                                                        |
| ------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| Context growth over a long session          | Transcript elision, ledger cap, 40-proposal ceiling                                               |
| Lost update on `search.yaml`                | Read-modify-write under `scout_lock()`, idempotent append; cross-process race documented above    |
| Agent proposes a tracker or redirect URL    | ADR-0008 egress gateway plus `identify_host` at both probe and approval                           |
| Losing the one-shot flow's speed            | The first turn *is* the one-shot flow — one message, proposals returned; refinement is optional   |
| Merged persona dilutes either specialty     | One persona, but the source and search-term research rules stay separate instruction blocks rather than being paraphrased into one; `stream_enabled` is orthogonal, so a regression here is a prompt edit, not a rollback |
