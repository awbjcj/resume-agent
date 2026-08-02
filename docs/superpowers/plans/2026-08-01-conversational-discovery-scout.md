# Conversational Discovery Scout Implementation Plan

> **Execution constraint:** Implement task-by-task in-line on the current branch. Do not use subagents or create a worktree. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the two one-shot discovery dialogs with one durable, streaming Discovery Scout that proposes company sources and search terms, learns from explicit dismissals, and writes configuration only after deterministic human approval.

**Architecture:** A single read-only Scout persona streams prose and tool activity through the existing conversational substrate, while a formatter projects permissive turn-draft models that Python normalizes into strict persisted proposals. A `SessionStore`-backed ledger owns durable turns and proposal state; service-layer post-processing performs canonical dedupe and bounded source probing, and deterministic approval endpoints are the only write path into `connectors.yaml` or `search.yaml`. The React page reuses the shared chat primitives and places a responsive proposal rail beside the transcript.

**Tech Stack:** Python 3.13 · FastAPI 0.115+ · Pydantic 2.13+ · Agno · Typer · pytest · React 19 · TypeScript 6 · TanStack Query 5 · Base UI/shadcn · Tailwind CSS 4 · Vitest

## Global Constraints

- This is spec 2 of 2 and consumes the existing streaming substrate unchanged: `AgentRunner.stream()`, `sessions/stream.py`, `sessions/turns.py`, `SessionStore`, `GET /api/runs/{id}/stream`, `useChatStream(runId)`, and `web/src/components/chat/`.
- Tests stay offline: no API key, no network, and no browser. Use recording runners, fake stream events, and monkeypatched `preview_source`/`add_source` calls.
- The Scout agent has read-only tools only: provider web-search tools plus `check_source`. It never receives a config, source-add, file-write, or approval tool.
- Human-triggered service functions remain the sole write boundary for `connectors.yaml`, `search.yaml`, and proposal status.
- Maximums are exact: 8 proposals per turn, 40 pending proposals per session, and 200 characters per dismissal reason.
- Sessions are append-only JSON at `<workspace>/scout/session-<id>.json`; only proposal resolution, session lifecycle, archival state, and the standing `goal` mutate in place.
- One unended Scout session is allowed per workspace. Ending blocks new turns but does not block approval or dismissal of pending proposals.
- Proposal URLs and citation URLs are untrusted. Positive source proposals and every rendered citation require HTTP(S); every source probe and approval continues through the existing ADR-0008 egress path.
- The server, not the browser, enforces that `avoid`, `failed`, `duplicate`, and unresolved `new` source checks are not approvable, and that an `unverified` scrape target requires `browser_enabled=true`.
- UI motion is restrained: no keyboard-triggered animation; transitions name exact properties, use the existing strong ease-out token, stay at 150–200ms, and remove transform motion under `prefers-reduced-motion`.
- Regenerate contracts once the backend routes and schemas are coherent. Primary command: `bash scripts/gen_ts_client.sh`; the Windows CRLF fallback is documented in Task 8.
- Focused verification follows each task. The final task runs the complete Python suite, web suite, linters, build, OpenAPI drift gate, and `git diff --check` before completion is claimed.
- Execute on the current branch as requested. Preserve unrelated checkout changes and keep every edit scoped to this feature.

## Correctness Amendments

These decisions are authoritative over any abbreviated code excerpt later in the plan.

1. **Separate formatter input from durable state.** `ScoutTurnDraft` and `ScoutProposalDraft` are permissive enough for `format_with_retry` to classify malformed payload combinations as `ProposalRejected`. `ScoutProposal` remains the strict stored model with the exactly-one-payload `model_validator`. This avoids Pydantic rejecting the formatter output before the required retry/degradation path can run.
2. **Never trust model-authored state.** Proposal ids, `check`, ATS/token/count/error fields, `status`, dismissal fields, and timestamps are created or overwritten by Python. The formatter can supply only kind, proposed payload, disposition (`propose`/`avoid`), reason, score, and citations.
3. **Preallocate the first session id in the router.** `POST /api/scout/sessions` puts that id in run metadata before work launches, enabling refresh recovery. The session file is created only when the first turn has completed formatting, post-processing, and cancellation checkpoints, so a stopped or failed first turn leaves no active shell session.
4. **Count raw accepted rows against the pending cap.** The 40-row cap is checked before probing and includes all stored rows whose `status` is `pending`, even rows whose `check` becomes `duplicate`, `avoid`, or `failed`. Users can dismiss those rows to release capacity.
5. **Deduplicate deterministically at two levels.** Existing config dedupe uses canonical URL/ATS keys for sources and destination-field plus case-folded value for terms. Session dedupe additionally uses normalized company names so an `avoid` row without a careers URL cannot be proposed again under the same company name.
6. **Assign proposal ids under the store lock.** `apply_turn_delta` assigns `p{N}` ids from the durable proposal count and writes those exact ids into the Scout turn record. Service code never predicts ids from an unlocked snapshot.
7. **Make config-first approval recoverable.** Approval holds `scout_lock()` across config inspection/write and proposal resolution. Before writing, it rechecks current config; if the target is already present, it marks the pending proposal `added` without another write. This recovers from concurrent Settings changes and from a prior config write whose later session write failed.
8. **Preserve streamed-message truth.** With streaming enabled, stored Scout text is the prose emitted above `---METADATA---`, verbatim. With streaming disabled, the formatter's `message` is authoritative. Structural failure after the retry stores prose plus a durable notice and no proposals; repeated proposal-integrity failure drops all proposals but keeps a valid goal update and reply.
9. **Keep recap cancellation atomic.** `end` sets `status="ended"` only after the streamed recap has formatted and passed the last checkpoint. Stop or provider failure leaves the session active and byte-equivalent.
10. **Expose runtime scrape capability in the view, not persistence.** `ScoutSessionOut.scrapeAvailable` and `scrapeUnavailableReason` are computed from current settings. They are not stored in session JSON and therefore cannot go stale.
11. **Batch approval is sequential and honest.** “Add all validated” calls the same approval endpoint once per currently pending validated proposal, continues after individual failures, and renders the error on the affected card. It does not include unverified scrape targets.
12. **First-run recovery is a distinct UI state.** A rehydrated `scout-start` run may have a session id before a session file exists. The page attaches the stream from run metadata without issuing a detail query until the run completes; subsequent `scout-turn` and `scout-end` recovery requires the matching session id.
13. **Formatter drafts defer semantic validation to Python.** Draft `kind`, `term_kind`, `disposition`, and `fit_score` fields use permissive scalar types. `normalize_turn` classifies unknown vocabulary, out-of-range scores, and invalid payload combinations as `TurnRejected`/`ProposalRejected`, so `format_with_retry` can perform its required retry and degradation. Strict literals and ranges remain on persisted models and wire schemas.
14. **Only source proposals can be negative evidence.** `disposition="avoid"` is valid only for a source row with a non-empty company and at least one HTTP(S) citation. Search-term rows are always positive suggestions. Positive sources require a non-empty company and HTTP(S) careers URL; term rows require a non-empty value.
15. **Reasoning UI means provider-safe summaries.** The stream may render provider-supplied reasoning summaries or progress events, but never raw hidden chain-of-thought. The service does not persist reasoning parts in Scout session JSON.
16. **Lifecycle cannot race a turn.** Archive, unarchive, and delete reject with `409 SCOUT_BUSY` while a matching `scout-start`, `scout-turn`, or `scout-end` run is active. Approval and dismissal remain allowed during a turn because their locked mutation is merged by the turn's final locked reload.
17. **CLI command indexes are snapshotted per command.** `add <n…>` resolves every number to a proposal id before the first approval. The visible index is rebuilt only after the whole command, preventing earlier approvals from retargeting later numbers.

---

## API and Interface Contract

The API skill's contract-first rules apply here: every boundary has typed input/output, validation stays at external boundaries, response shapes do not vary by branch, and existing one-shot routes are removed only in the same change that introduces their replacement.

| Method | Path | Request | Success | Deterministic errors |
| --- | --- | --- | --- | --- |
| `POST` | `/api/scout/sessions` | `ScoutMessageIn` | `202 RunOut` | `400 SETUP_INCOMPLETE`, `400 SEARCH_DISABLED`, `409 SESSION_ACTIVE`, `409 SCOUT_BUSY` |
| `POST` | `/api/scout/sessions/{session_id}/messages` | `ScoutMessageIn` | `202 RunOut` | `404 NOT_FOUND`, `409 CONFLICT`, `409 SCOUT_BUSY` |
| `POST` | `/api/scout/sessions/{session_id}/proposals/{proposal_id}/approve` | none | `200 ScoutSessionOut` | `404 NOT_FOUND`, `409 CONFLICT` |
| `POST` | `/api/scout/sessions/{session_id}/proposals/{proposal_id}/dismiss` | `ScoutDismissIn` | `200 ScoutSessionOut` | `404 NOT_FOUND`, `409 CONFLICT`, `422 VALIDATION_ERROR` |
| `POST` | `/api/scout/sessions/{session_id}/end` | none | `202 RunOut` | `404 NOT_FOUND`, `409 CONFLICT`, `409 SCOUT_BUSY` |
| `GET` | `/api/scout/sessions` | `includeArchived`, optional `status` | `200 ScoutSessionsOut` | `422` from typed query validation |
| `GET` | `/api/scout/sessions/{session_id}` | none | `200 ScoutSessionOut` | `404 NOT_FOUND` |
| `POST` | `/api/scout/sessions/{session_id}/archive` | none | `200 ScoutSessionOut` | `404 NOT_FOUND`, `409 CONFLICT` |
| `POST` | `/api/scout/sessions/{session_id}/unarchive` | none | `200 ScoutSessionOut` | `404 NOT_FOUND`, `409 CONFLICT` |
| `DELETE` | `/api/scout/sessions/{session_id}` | none | `204` with no body | `404 NOT_FOUND` |

Run kinds are exactly `scout-start`, `scout-turn`, and `scout-end`; every run uses singleton key `scout` and metadata `{ "stream": true, "sessionId": <id>, "turnCount": <durable count> }`.

The session list intentionally preserves the approved `ScoutSessionsOut` shape and the repository's existing Coach/Interview history convention instead of introducing a second pagination contract in this feature. `includeArchived` and optional `status` remain the only list filters; pagination can be added later as an additive envelope migration shared by all session kinds.

## Frontend Design Translation

| Before | After | Why |
| --- | --- | --- |
| Two modal, one-shot forms hidden behind Sources and Search settings | Dedicated `/scout` workspace with one transcript and one proposal rail | Refinement, history, and visible work need persistent spatial context |
| Spinner while research and validation are opaque | Streaming prose, reasoning disclosure, and live web-search/`check_source` chips | Users see progress that explains perceived latency |
| Table checkbox conflates validation and user resolution | Badge reads `status` first, then `check`; actions remain explicit | “Added” and “validated” are different contracts |
| Results disappear when a dialog closes | Durable sessions with archive/unarchive/delete history | Feedback and decisions survive navigation and refresh |
| Bulk selection fails as one undifferentiated action | Sequential “Add all validated” with per-card errors | A single bad source does not hide successful approvals |
| Desktop-width modal table | Transcript/rail at `xl`, stacked rail below chat on smaller screens | Cards remain readable and actions stay touch-friendly |
| Generic animated state changes | Exact `opacity`, `transform`, `border-color`, and `background-color` transitions at 150–200ms; reduced-motion removes movement | Motion communicates state without making a frequently used chat feel slow |

## File Structure

### Create

| Path | Responsibility |
| --- | --- |
| `src/resume_agent/discovery/scout.py` | Turn-draft schemas, normalization, merged persona/formatter agents, prompt rendering constants, `check_source` tool |
| `src/resume_agent/discovery/scout_store.py` | Strict session/proposal models and all `SessionStore` lifecycle/mutation functions |
| `src/resume_agent/services/scout_context.py` | Profile/config grounding, canonical source/term/session dedupe keys, ledger/goal/transcript rendering |
| `src/resume_agent/services/scout.py` | Start/message/recap orchestration, probe fan-out, views, approve, dismiss |
| `src/resume_agent/api/schemas/scout.py` | Camel-case request and response contracts |
| `src/resume_agent/api/routers/scout.py` | Run-backed turn routes and deterministic proposal/lifecycle routes |
| `tests/test_scout.py` | Draft normalization, merged-agent tool boundary, prompt contract |
| `tests/test_scout_store.py` | Strict persistence invariants, ids, caps, lifecycle, concurrent resolution |
| `tests/test_scout_context.py` | Grounding, canonicalization, config/session dedupe, ledger and transcript elision |
| `tests/test_scout_service.py` | Streaming, degradation, dedupe/probe, approval/dismissal, recap atomicity |
| `tests/api/test_scout_router.py` | HTTP schema, guards, metadata, lifecycle, error mapping |
| `web/src/features/scout/use-scout.ts` | Generated-contract queries/mutations and run tracking |
| `web/src/features/scout/use-scout.test.tsx` | Endpoint, invalidation, and batch mutation behavior |
| `web/src/features/scout/ProposalCard.tsx` | Badge precedence, citations, Add/Dismiss, per-row error |
| `web/src/features/scout/ProposalCard.test.tsx` | Card states, server gates reflected in UI, accessibility |
| `web/src/features/scout/ProposalRail.tsx` | Proposal ordering and sequential Add-all workflow |
| `web/src/features/scout/ProposalRail.test.tsx` | Batch continuation and resolved-row behavior |
| `web/src/features/scout/ScoutPage.tsx` | First prompt, chat stream/recovery, composer, rail, recap, session history |
| `web/src/features/scout/ScoutPage.test.tsx` | Start/refine/stop/retry/recovery/responsive/session workflows |

### Modify

| Path | Change |
| --- | --- |
| `src/resume_agent/api/app.py` | Include the Scout router |
| `src/resume_agent/api/deps.py` | Add `get_scout_dir(request)` using the same workspace-root resolution as interviews |
| `src/resume_agent/api/routers/sources.py` | Remove both one-shot discovery routes/imports; keep source CRUD/preview unchanged |
| `src/resume_agent/api/schemas/sources.py` | Remove `DiscoverSourcesIn` and `DiscoverSearchIn` |
| `src/resume_agent/prompts/registry.py` | Replace four stale Scout guidance entries with `discovery-scout` and `discovery-scout-format` |
| `src/resume_agent/cli.py` | Replace one-shot `scout` and `scout-search` with the conversational loop |
| `tests/test_cli_scout.py` | Exercise the shared service path and command parser |
| `tests/test_prompt_registry.py` | Assert new prompt projections and stale-key absence |
| `tests/api/test_openapi_contract.py` | Keep the existing drift assertion; regenerated artifacts supply the new expectation |
| `contracts/openapi.json` | Regenerated API contract |
| `contracts/ts/api.ts` | Regenerated TypeScript contract |
| `web/src/lib/api/schema.ts` | Regenerated SPA contract copy |
| `web/src/app/router.tsx` | Lazy `/scout` route |
| `web/src/app/AppLayout.tsx` | “Discovery Scout” sidebar item under Find & tailor |
| `web/src/features/sources/SourcesPage.tsx` | Replace dialog trigger with “Ask the Scout” link |
| `web/src/features/sources/SourcesPage.test.tsx` | Assert link target and retained source controls |
| `web/src/features/settings/pages/SearchSettingsPage.tsx` | Replace suggestion dialog with “Ask the Scout” link |
| `web/src/index.css` | Scout card state transitions and reduced-motion override |

### Delete after replacement coverage passes

- `src/resume_agent/discovery/source_scout.py`
- `src/resume_agent/discovery/search_scout.py`
- `src/resume_agent/services/source_discovery.py`
- `src/resume_agent/services/search_discovery.py`
- `tests/test_source_scout.py`
- `tests/test_search_scout.py`
- `tests/test_source_discovery.py`
- `tests/test_search_discovery.py`
- `tests/test_source_discovery_enrichment.py`
- `tests/test_search_discovery_enrichment.py`
- `tests/test_scout_research_agent_wiring.py`
- `tests/api/test_search_discover_router.py`
- `web/src/features/sources/DiscoverCompaniesDialog.tsx`
- `web/src/features/sources/DiscoverCompaniesDialog.test.tsx`
- `web/src/features/sources/use-discover.ts`
- `web/src/features/search-scout/SuggestSearchTermsDialog.tsx`
- `web/src/features/search-scout/SuggestSearchTermsDialog.test.tsx`
- `web/src/features/search-scout/use-search-discover.ts`

---

### Task 1: Define Scout turn contracts, validation, and read-only agents

**Files:**

- Create: `src/resume_agent/discovery/scout.py`
- Create: `tests/test_scout.py`
- Modify: `src/resume_agent/prompts/registry.py`
- Modify: `tests/test_prompt_registry.py`

**Interfaces:**

- Consumes: `Citation`, `is_http_url`, `TurnRejected`, `Runner`, `build_search_equipped`, `with_guidance`.
- Produces: `SuggestionKind`; `ScoutTurnDraft`; `ValidatedScoutTurn`; `ProposalRejected`; `normalize_turn(turn, session, *, strict=True)`; `normalize_recap(turn, session, strict=True)`; `build_scout_agent(check_source)`; `build_scout_formatter_agent()`; `make_check_source_tool(search_path)`.

- [ ] **Step 1: Write failing normalization and tool-boundary tests**

```python
def test_normalize_drops_all_proposals_after_second_integrity_failure():
    turn = ScoutTurnDraft(
        message="I found one lead.",
        proposals=[ScoutProposalDraft(kind="source", source=None, term=None)],
    )
    with pytest.raises(ProposalRejected, match="exactly one payload"):
        normalize_turn(turn, {"proposals": []}, strict=True)
    degraded = normalize_turn(turn, {"proposals": []}, strict=False)
    assert degraded.message == "I found one lead."
    assert degraded.proposals == []
    assert degraded.notice == "Proposals were omitted because their details could not be validated."


def test_positive_source_and_citations_require_http_urls():
    bad = ScoutTurnDraft.model_validate({
        "message": "Found it",
        "proposals": [{
            "kind": "source",
            "source": {"company": "Acme", "url": "file:///etc/passwd"},
            "reason": "fit",
            "citations": [{"url": "javascript:alert(1)", "title": "bad"}],
        }],
    })
    with pytest.raises(ProposalRejected):
        normalize_turn(bad, {"proposals": []})


def test_agent_tools_are_search_plus_check_source(monkeypatch):
    seen = {}
    monkeypatch.setattr(scout, "build_search_equipped", fake_search_builder(seen))
    scout.build_scout_agent(lambda _url: "{}")
    assert seen["tool_names"] == ["web_search", "check_source"]
```

- [ ] **Step 2: Run the tests and verify the new module is missing**

Run: `.venv\Scripts\python.exe -m pytest tests/test_scout.py tests/test_prompt_registry.py -q`

Expected: collection fails because `resume_agent.discovery.scout` does not exist.

- [ ] **Step 3: Add the draft models and normalization contract**

```python
PROPOSAL_CAP = 8
PENDING_CAP = 40
GOAL_CHAR_CAP = 2_000

SuggestionKind = Literal[
    "keyword", "title", "role_anchor", "exclude_term",
    "location", "seniority", "adjacent_role",
]

class SourceDraft(ExtensibleModel):
    company: str = ""
    url: str = ""

class TermDraft(ExtensibleModel):
    value: str = ""
    term_kind: str = "keyword"

class ScoutProposalDraft(ExtensibleModel):
    kind: str = "source"
    source: SourceDraft | None = None
    term: TermDraft | None = None
    disposition: str = "propose"
    reason: str = ""
    fit_score: int | None = None
    citations: list[Citation] = Field(default_factory=list)

class ScoutTurnDraft(ExtensibleModel):
    kind: str = "reply"
    message: str = ""
    goal_update: str | None = None
    proposals: list[ScoutProposalDraft] = Field(default_factory=list)

@dataclass
class ValidatedScoutTurn:
    message: str
    goal_update: str | None = None
    proposals: list[ScoutProposalDraft] = field(default_factory=list)
    notice: str = ""

class ProposalRejected(TurnRejected):
    """A proposal failed URL, payload, vocabulary, or evidence integrity."""
```

`normalize_turn` must reject empty reply text, recap on a normal turn, unknown turn/proposal vocabulary, more than eight rows, an empty/oversized goal update, or a result that would exceed 40 pending rows as structural `TurnRejected`. It validates every proposal into a cleaned copy, including the strict fit-score range and the source-only `avoid` rule; a strict integrity failure raises `ProposalRejected`, while lenient mode returns the reply and goal update with zero proposals and the durable notice above. `normalize_recap` requires `kind="recap"`, non-empty message, and no proposals or goal update.

- [ ] **Step 4: Merge the two instruction sets and build the agents**

The persona instructions must keep source and term rules as separate blocks, add the prose/metadata delimiter contract, label all profile/config/transcript/tool material untrusted, forbid configuration writes, require at most eight rows, and require an evidence citation for every `avoid` row. The formatter uses `ScoutTurnDraft`, copies only explicit fields, and never invents URLs, terms, scores, citations, or negative signals.

`make_check_source_tool(search_path)` retains the existing five-role bounded call to `preview_source(url, search_path=search_path, limit=5, browser=False)`, always returns JSON, and converts every exception to `{ "ok": false, "error_code": "PROBE_ERROR" }`.

- [ ] **Step 5: Replace prompt registry projections**

```python
_spec(
    "discovery-scout",
    "Discovery Scout",
    "discovery",
    "Researches company sources and search conditions in a conversational session.",
    scout._SCOUT_INSTRUCTIONS,
),
_spec(
    "discovery-scout-format",
    "Discovery Scout formatter",
    "discovery",
    "Formats grounded Scout notes into a validated conversational turn.",
    scout._FORMAT_INSTRUCTIONS,
),
```

Assert `SPECS_BY_KEY` contains these two keys and excludes all four legacy `source-scout-*`/`search-scout-*` keys.

- [ ] **Step 6: Run focused tests and commit**

Run: `.venv\Scripts\python.exe -m pytest tests/test_scout.py tests/test_prompt_registry.py -q`

Expected: PASS.

```powershell
git add src/resume_agent/discovery/scout.py src/resume_agent/prompts/registry.py tests/test_scout.py tests/test_prompt_registry.py
git commit -m "feat: define conversational scout contracts"
```

---

### Task 2: Add strict durable Scout sessions and proposal mutations

**Files:**

- Create: `src/resume_agent/discovery/scout_store.py`
- Create: `tests/test_scout_store.py`

**Interfaces:**

- Consumes: `SessionModel`, `SessionStore`, `now_iso`, `Citation`, `SuggestionKind`.
- Produces: the approved `SourcePayload`, `TermPayload`, `ScoutProposal`, `ScoutTurnRecord`, and `ScoutSession` models; `scout_dir`; `scout_lock`; `active_session`; `load_session`; `list_sessions`; `create_session_from_turn`; `apply_turn_delta`; `set_proposal_status`; `end_session`; archive/unarchive/delete wrappers.

- [ ] **Step 1: Write failing model, id, and lifecycle tests**

```python
def test_proposal_requires_exactly_one_matching_payload():
    with pytest.raises(ValidationError):
        ScoutProposal(kind="source")
    with pytest.raises(ValidationError):
        ScoutProposal(kind="source", source=SourcePayload(), term=TermPayload())
    with pytest.raises(ValidationError):
        ScoutProposal(kind="search_term", source=SourcePayload(company="Acme"))


def test_create_and_append_assign_ids_under_lock(tmp_path):
    first = create_session_from_turn(
        tmp_path, "abc", goal="AI infra", user_text="AI infra",
        scout_turn=ScoutTurnRecord(role="scout", text="First"),
        proposals=[source_proposal("Modal")],
    )
    second = apply_turn_delta(
        tmp_path, "abc", user_text="smaller",
        scout_turn=ScoutTurnRecord(role="scout", text="Second"),
        proposals=[term_proposal("inference serving")], goal_update="seed-stage AI infra",
    )
    assert [row["id"] for row in second["proposals"]] == ["p1", "p2"]
    assert second["turns"][-1]["proposal_ids"] == ["p2"]
    assert second["goal"] == "seed-stage AI infra"
    assert load_session(tmp_path, "abc") == second
```

Also cover one-active-session enforcement, archived filtering, ended-session turn rejection, late proposal resolution after end, reason/timestamp persistence, and delete not touching config files.

- [ ] **Step 2: Run the tests and verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests/test_scout_store.py -q`

Expected: collection fails because the store module is missing.

- [ ] **Step 3: Implement the strict models**

Use `Field(default_factory=list)` for every list and an after-validator returning `Self`:

```python
class ScoutProposal(ExtensibleModel):
    id: str = ""
    kind: Literal["source", "search_term"] = "source"
    source: SourcePayload | None = None
    term: TermPayload | None = None
    reason: str = ""
    fit_score: int | None = Field(default=None, ge=0, le=100)
    citations: list[Citation] = Field(default_factory=list)
    check: Literal["validated", "unverified", "failed", "duplicate", "avoid", "new"] = "new"
    check_error: str = ""
    status: Literal["pending", "added", "dismissed"] = "pending"
    dismiss_reason: str = ""
    resolved_at: str | None = None

    @model_validator(mode="after")
    def exactly_one_payload(self) -> Self:
        if (self.source is None) == (self.term is None):
            raise ValueError("exactly one proposal payload is required")
        if self.kind == "source" and self.source is None:
            raise ValueError("source proposal requires source payload")
        if self.kind == "search_term" and self.term is None:
            raise ValueError("search-term proposal requires term payload")
        return self
```

`TermPayload` carries the seven-value `SuggestionKind` and retains an after-validator that rejects a `seniority` value outside `internship`, `entry`, `associate`, `mid-senior`, `director`, and `executive`. The draft normalizer performs the same check so invalid formatter output reaches `ProposalRejected`; the stored validator protects non-agent callers and JSON reloads.

- [ ] **Step 4: Implement locked delta application and lifecycle wrappers**

Both creation and append call a private `_append_turn` while holding `_STORE.lock()`. `_append_turn` rechecks the eight-row turn limit and `current pending + new rows <= 40`, assigns ids starting at `len(session["proposals"]) + 1`, stamps both turns with one `now_iso()`, attaches the generated ids only to the Scout turn, updates `goal` only after the turn is accepted, and validates the complete session before atomic write.

`set_proposal_status(workspace_root, session_id, proposal_id, status, reason="")` accepts only `pending` rows, stamps `resolved_at`, and stores a reason only for `dismissed`. `end_session` appends `kind="recap"`, sets `recap`, `ended_at`, and `status="ended"`; it does not modify proposal statuses.

- [ ] **Step 5: Run focused tests and commit**

Run: `.venv\Scripts\python.exe -m pytest tests/test_scout_store.py -q`

Expected: PASS.

```powershell
git add src/resume_agent/discovery/scout_store.py tests/test_scout_store.py
git commit -m "feat: persist scout sessions and proposal state"
```

---

### Task 3: Consolidate grounding, feedback ledger, and dedupe keys

**Files:**

- Create: `src/resume_agent/services/scout_context.py`
- Create: `tests/test_scout_context.py`

**Interfaces:**

- Consumes: connector/search loaders, source views, profile facts/matrix, stored session dictionaries.
- Produces: `_EXISTING_FIELD`; `scout_context(connectors_path, search_path, profile_dir)`; `_canonical_url`; `_candidate_keys`; `_existing_keys`; `_existing_terms`; `session_source_keys`; `session_term_keys`; `render_goal`; `render_ledger`; `render_transcript`.

- [ ] **Step 1: Write failing context and feedback tests**

```python
def test_ledger_renders_added_and_dismissed_reason_as_untrusted(tmp_path):
    session = session_dict(
        proposals=[
            proposal("p1", "Modal", status="added"),
            proposal("p2", "Scale AI", status="dismissed", reason="too big"),
        ]
    )
    text = render_ledger(session)
    assert "ALREADY ADDED: Modal" in text
    assert "DISMISSED — DO NOT PROPOSE AGAIN:" in text
    assert "Scale AI — user said: too big" in text
    assert "UNTRUSTED USER FEEDBACK" in text


def test_session_keys_dedupe_avoid_without_url_by_company():
    keys = session_source_keys(session_dict(proposals=[avoid("p1", "Acme")]))
    assert "company:acme" in keys


def test_transcript_keeps_recent_tail_and_marks_elision():
    rendered = render_transcript(long_session(), char_cap=240)
    assert len(rendered) <= 240
    assert "older turns elided" in rendered
    assert "latest user message" in rendered
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests/test_scout_context.py -q`

Expected: collection fails because `services.scout_context` is missing.

- [ ] **Step 3: Move and unify context helpers**

Build one deterministic prompt block containing recent profile titles, top 15 skills, current keywords, titles, role anchors, exclude terms, locations, seniority levels, and existing source display names. Every optional artifact degrades to `(none)` without hiding malformed required data beyond the existing loaders' behavior.

Keep `_canonical_url`, ATS-token extraction, `_existing_keys`, and `_existing_terms` behavior byte-compatible with the old services. `_EXISTING_FIELD` remains:

```python
_EXISTING_FIELD = {
    "keyword": "keywords",
    "title": "titles",
    "role_anchor": "role_anchors",
    "exclude_term": "exclude_terms",
    "location": "locations",
    "seniority": "experience_levels",
    "adjacent_role": "titles",
}
```

- [ ] **Step 4: Implement bounded goal, ledger, and transcript rendering**

`render_goal` labels the standing brief as untrusted user data. `render_ledger` includes all added proposal labels and the 20 most recent dismissed rows with reasons, followed by an omitted-count line. `render_transcript` uses a 12,000-character cap, keeps the newest complete turn lines, and inserts `[… older turns elided …]`; it never cuts the untrusted framing label away.

- [ ] **Step 5: Run focused tests and commit**

Run: `.venv\Scripts\python.exe -m pytest tests/test_scout_context.py -q`

Expected: PASS.

```powershell
git add src/resume_agent/services/scout_context.py tests/test_scout_context.py
git commit -m "feat: build scout context and feedback ledger"
```

---

### Task 4: Implement streamed turns, deterministic dedupe, and source probing

**Files:**

- Create: `src/resume_agent/services/scout.py`
- Create: `tests/test_scout_service.py`

**Interfaces:**

- Consumes: Tasks 1–3 plus `persona_output`, `format_with_retry`, `gather_isolated`, `preview_source`, `StreamSink`.
- Produces: `run_start_turn`; `run_message_turn`; `run_recap_turn`; `session_view`; `sessions_view`.

- [ ] **Step 1: Write failing streaming and post-pass tests**

Add recording fakes that exercise:

```python
def test_dismissed_feedback_is_in_next_prompt(tmp_path):
    seed_dismissed_session(tmp_path, company="Scale AI", reason="too big")
    runner = RecordingStreamingRunner(reply_turn())
    run_message_turn(
        reporter(), workspace_root=tmp_path, session_id="s1",
        message="find smaller ones",
        connectors_path=str(tmp_path / "config" / "connectors.yaml"),
        search_path=str(tmp_path / "config" / "search.yaml"),
        profile_dir=tmp_path / "profile", browser_enabled=False,
        scout_agent=runner, formatter_agent=formatter(),
    )
    assert "DISMISSED — DO NOT PROPOSE AGAIN" in runner.prompts[0]
    assert "Scale AI — user said: too big" in runner.prompts[0]


def test_streamed_prose_is_stored_and_probe_events_precede_completed(tmp_path):
    sink = RecordingSink()
    view = run_start_turn(
        reporter(), workspace_root=tmp_path, session_id="s1", message="AI infra",
        connectors_path=str(tmp_path / "config" / "connectors.yaml"),
        search_path=str(tmp_path / "config" / "search.yaml"),
        profile_dir=tmp_path / "profile", browser_enabled=False, sink=sink,
        scout_agent=streaming_runner("Found two strong options.", tools=["web_search"]),
        formatter_agent=formatter(),
    )
    assert view["turns"][-1]["text"] == "Found two strong options."
    assert "".join(event.text for event in sink.events if isinstance(event, TextDelta)) == "Found two strong options."
    assert [type(event).__name__ for event in sink.events if isinstance(event, (ToolStarted, ToolCompleted))] == [
        "ToolStarted", "ToolCompleted"
    ]


def test_repeated_session_source_and_term_become_duplicate(tmp_path):
    view = run_message_turn(
        reporter(), workspace_root=tmp_path, session_id="s1", message="more",
        connectors_path=str(tmp_path / "config" / "connectors.yaml"),
        search_path=str(tmp_path / "config" / "search.yaml"),
        profile_dir=tmp_path / "profile", browser_enabled=False,
        scout_agent=repeated_proposals_runner(), formatter_agent=formatter(),
    )
    assert [row["check"] for row in view["proposals"][-2:]] == ["duplicate", "duplicate"]
```

Also assert: eight rows pass; nine degrade structurally to prose+notice; 40 pending pass and 41 degrade; avoid skips `preview_source`; fresh source probes run through `gather_isolated`; an isolated exception becomes `failed`; citation integrity retry drops all proposals and notice survives reload; `stream_enabled=false` uses formatter text; cancellation at every provider/probe event leaves the session byte-equivalent. Do not assert that a short prose delta precedes a tool event: the unchanged `ProseEmitter` may hold short text until it can exclude a split metadata delimiter. Assert reconstructed prose and tool-event ordering independently.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests/test_scout_service.py -q`

Expected: collection fails because `services.scout` is missing.

- [ ] **Step 3: Implement the shared turn pipeline**

Use these exact public signatures:

- `run_start_turn(reporter, *, workspace_root: Path, session_id: str, message: str, connectors_path: str, search_path: str, profile_dir: Path, browser_enabled: bool, scout_agent: Runner | None = None, formatter_agent: Runner | None = None, sink: StreamSink | None = None) -> dict`
- `run_message_turn(reporter, *, workspace_root: Path, session_id: str, message: str, connectors_path: str, search_path: str, profile_dir: Path, browser_enabled: bool, scout_agent: Runner | None = None, formatter_agent: Runner | None = None, sink: StreamSink | None = None) -> dict`

A private `_run_turn` strips the user message, rejects empty or more than 2,000 characters for CLI/internal callers, assembles `scout_context + render_goal + render_ledger + render_transcript + latest untrusted message`, calls `persona_output(scout_agent, prompt, output_sink, reporter, source="scout notes")`, formats with label `SCOUT NOTES`, applies structural/integrity degradation, performs the post-pass, calls a final `reporter.checkpoint()`, then uses `create_session_from_turn` or `apply_turn_delta`.

- [ ] **Step 4: Implement authoritative proposal conversion and ranking**

For each cleaned draft, construct a new strict `ScoutProposal` and ignore all extra/state-looking draft fields. Process in original formatter order for dedupe, then rank the completed turn by `(check rank, negative fit score, original index)` using `validated`, `unverified`, `new`, `avoid`, `failed`, `duplicate`. Prior-session keys and current-turn seen keys both participate.

Fresh source probes use:

```python
results = asyncio.run(gather_isolated(
    fresh,
    lambda item: asyncio.to_thread(
        preview_source, item[1].source.url,
        search_path=search_path, browser=False,
    ),
    on_complete=reporter.step,
    checkpoint=reporter.checkpoint,
))
```

Map successful previews to `validated`; `ATS_NOT_DETECTED` to `unverified`; all other results to `failed`. Copy only the preview's canonical URL, ATS kind, token, role count, error code, and safe error text into persisted fields.

- [ ] **Step 5: Implement stable camel-case views**

`session_view(workspace_root, session_id, *, browser_enabled)` returns every model field in camelCase plus computed `scrapeAvailable` and `scrapeUnavailableReason`. `sessions_view` returns summaries containing id, goal, timestamps, lifecycle, proposal count, pending count, added count, and dismissed count. These same dictionaries are safe as run results and HTTP response-model inputs.

- [ ] **Step 6: Implement streamed recap without freezing proposals**

`run_recap_turn` requires an active session, prompts from goal + ledger + transcript, formats through `normalize_recap`, stores streamed prose when enabled, and calls `end_session` only after the final checkpoint. The recap prompt explicitly requests added, dismissed, and still-pending counts and labels.

- [ ] **Step 7: Run focused tests and commit**

Run: `.venv\Scripts\python.exe -m pytest tests/test_scout.py tests/test_scout_store.py tests/test_scout_context.py tests/test_scout_service.py -q`

Expected: PASS.

```powershell
git add src/resume_agent/services/scout.py tests/test_scout_service.py
git commit -m "feat: run streaming scout turns"
```

---

### Task 5: Add deterministic approval and dismissal services

**Files:**

- Modify: `src/resume_agent/services/scout.py`
- Modify: `tests/test_scout_service.py`

**Interfaces:**

- Consumes: `scout_lock`, config/dedupe helpers, `ConfigStore`, `SearchConfigDoc`, `add_source`.
- Produces: `approve_proposal(workspace_root, session_id, proposal_id, *, config_store, connectors_path, search_path, browser_enabled) -> dict`; `dismiss_proposal(workspace_root, session_id, proposal_id, *, reason, browser_enabled) -> dict`.

- [ ] **Step 1: Add failing write-boundary tests**

```python
def test_term_approval_preserves_unrelated_fields_and_is_idempotent(tmp_path):
    store = YamlConfigStore(tmp_path / "config")
    store.put("search", SearchConfigDoc(keywords=["python"], min_salary=180_000))
    view = approve_proposal(
        tmp_path, "s1", "p1", config_store=store,
        connectors_path=str(tmp_path / "config" / "connectors.yaml"),
        search_path=str(tmp_path / "config" / "search.yaml"),
        browser_enabled=False,
    )
    saved = store.get("search")
    assert saved.keywords == ["python", "inference serving"]
    assert saved.min_salary == 180_000
    assert view["proposals"][0]["status"] == "added"


def test_config_already_contains_pending_term_marks_added_without_put(tmp_path):
    store = RecordingConfigStore(SearchConfigDoc(keywords=["rust"]))
    approve_proposal(
        tmp_path, "s1", "p1", config_store=store,
        connectors_path=str(tmp_path / "config" / "connectors.yaml"),
        search_path=str(tmp_path / "config" / "search.yaml"),
        browser_enabled=False,
    )
    assert store.put_calls == []
    assert load_session(tmp_path, "s1")["proposals"][0]["status"] == "added"
```

Also test source provider selection (`validated -> auto`, `unverified -> scrape`), current-config recovery for sources, browser-disabled rejection, server rejection of `avoid`/`failed`/`duplicate`, already-resolved conflict, unknown ids, optional dismissal reason, 200-character service defense, and approval after session end.

- [ ] **Step 2: Run the added tests and verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests/test_scout_service.py -q`

Expected: FAIL because approval functions are missing.

- [ ] **Step 3: Implement approval under one process lock**

```python
def approve_proposal(workspace_root: Path | str, session_id: str, proposal_id: str,
                     *, config_store: ConfigStore, connectors_path: str,
                     search_path: str, browser_enabled: bool) -> dict:
    with scout_lock():
        session = load_session(workspace_root, session_id)
        proposal = _pending_proposal(session, proposal_id)
        if proposal["kind"] == "source":
            _approve_source(proposal, connectors_path, search_path, browser_enabled)
        else:
            _approve_term(proposal, config_store)
        set_proposal_status(workspace_root, session_id, proposal_id, "added")
    return session_view(workspace_root, session_id, browser_enabled=browser_enabled)
```

`_approve_term` performs case-insensitive destination-field recheck and `model_copy(update={field: [*values, value]})`. `_approve_source` rechecks `_existing_keys`; if absent, calls `add_source(provider="scrape" if check == "unverified" else "auto", url=source.url, label=source.company, country="com", connectors_path=connectors_path, search_path=search_path)`.

- [ ] **Step 4: Implement dismissal**

Strip the reason, reject more than 200 characters even for non-HTTP callers, allow dismissal of any pending check state, and call `set_proposal_status(workspace_root, session_id, proposal_id, "dismissed", reason=cleaned)` under the same lock. Return the complete updated view.

- [ ] **Step 5: Run focused tests and commit**

Run: `.venv\Scripts\python.exe -m pytest tests/test_scout_service.py -q`

Expected: PASS.

```powershell
git add src/resume_agent/services/scout.py tests/test_scout_service.py
git commit -m "feat: approve and dismiss scout proposals"
```

---

### Task 6: Expose the typed Scout HTTP API

**Files:**

- Create: `src/resume_agent/api/schemas/scout.py`
- Create: `src/resume_agent/api/routers/scout.py`
- Create: `tests/api/test_scout_router.py`
- Modify: `src/resume_agent/api/deps.py`
- Modify: `src/resume_agent/api/app.py`

**Interfaces:**

- Consumes: Task 4/5 services, `RunManager`, `launch`, `with_conversation_stream`, settings/config/workspace dependencies.
- Produces: every endpoint in the contract table; generated OpenAPI names `ScoutMessageIn`, `ScoutDismissIn`, `ScoutSessionOut`, `ScoutSessionsOut` and nested output models.

- [ ] **Step 1: Write failing router tests**

Cover the complete contract table, including:

```python
def test_start_preallocates_session_metadata_and_launches_stream(client, monkeypatch):
    response = client.post("/api/scout/sessions", json={"message": "AI infra"})
    assert response.status_code == 202
    body = response.json()
    assert body["kind"] == "scout-start"
    assert body["meta"] == {
        "stream": True, "sessionId": body["meta"]["sessionId"], "turnCount": 0
    }


def test_end_blocks_messages_but_allows_pending_approval(client, seeded_session):
    end = client.post(f"/api/scout/sessions/{seeded_session}/end")
    wait_for_run(client, end.json()["runId"])
    assert client.post(f"/api/scout/sessions/{seeded_session}/messages",
                       json={"message": "more"}).status_code == 409
    assert client.post(f"/api/scout/sessions/{seeded_session}/proposals/p1/approve").status_code == 200
```

Also assert setup/search guards, one-active conflict, singleton conflict, unknown mapping, 200-character request validation, archive filtering, unarchive/delete, `204` empty response body, and exact run metadata for message/end.

- [ ] **Step 2: Run router tests and verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests/api/test_scout_router.py -q`

Expected: collection fails because schemas/router are missing.

- [ ] **Step 3: Define wire models with narrow literals**

Use nested `CamelModel` classes and `Literal` values matching the domain. `ScoutMessageIn.message` is `Field(min_length=1, max_length=2_000)`; `ScoutDismissIn.reason` defaults to empty and is capped at 200. `ScoutSessionOut` includes computed scrape capability, and `ScoutSessionsOut.sessions` is always a list.

- [ ] **Step 4: Add workspace and setup dependencies**

```python
def get_scout_dir(request: Request):
    paths = get_workspace_paths(request)
    root = paths.root if paths is not None else request.app.state.data_dir
    return root / "scout"
```

The router passes `get_scout_dir(request).parent` as `workspace_root`. `_guard_setup` uses `missing_model_keys(settings)` and `plan_search(settings.mid_model, settings.search_mode)`; it returns `SETUP_INCOMPLETE` or `SEARCH_DISABLED` without launching work.

- [ ] **Step 5: Implement run-backed and deterministic routes**

Allocate `session_id = uuid.uuid4().hex` before `_submit` on start. `_submit` always wraps work with `with_conversation_stream`, uses singleton `scout`, and maps singleton conflicts to `SCOUT_BUSY`. Approval/dismissal call services synchronously and validate their dictionaries through `ScoutSessionOut`.

Map unknown session/proposal errors to `404 NOT_FOUND`; active/ended/resolved/not-approvable/archive conflicts to `409 CONFLICT`; remaining service validation to `422 VALIDATION_ERROR`. Continue using the repository's `ApiException` envelope.

- [ ] **Step 6: Wire the router and run API tests**

Run: `.venv\Scripts\python.exe -m pytest tests/api/test_scout_router.py tests/api/test_errors_router.py -q`

Expected: PASS.

```powershell
git add src/resume_agent/api/schemas/scout.py src/resume_agent/api/routers/scout.py src/resume_agent/api/deps.py src/resume_agent/api/app.py tests/api/test_scout_router.py
git commit -m "feat: expose conversational scout api"
```

---

### Task 7: Replace the CLI with the conversational service loop

**Files:**

- Modify: `src/resume_agent/cli.py`
- Modify: `tests/test_cli_scout.py`

**Interfaces:**

- Consumes: `active_session`, Scout service functions, `ConsoleStreamSink`, `NullSink`, `YamlConfigStore`.
- Produces: one `resume-agent scout [initial_message]` command; removes `scout-search`.

- [ ] **Step 1: Rewrite failing CLI tests around shared services**

Test a scripted prompt sequence `initial -> add 1 3 -> skip 2 too early stage -> end`, verify the service calls and session ids, and assert output contains tool activity plus numbered proposals. Add cases for resuming an active session, `quit` leaving it active, malformed/out-of-range commands, missing model/search setup, and `STREAM_ENABLED=false` printing the stored formatter message once.

- [ ] **Step 2: Run the tests and verify old command behavior fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_cli_scout.py -q`

Expected: FAIL because `scout` still runs the one-shot flow.

- [ ] **Step 3: Implement the loop and parser**

Keep the positional message optional for compatibility; prompt with `You` when absent. Resolve tenant-specific connectors, search, profile, and workspace roots once. Resume the active session when present; otherwise preallocate an id and call `run_start_turn`.

After every view, print all proposals in durable order with stable display indexes and labels. Resolved rows retain their number and show their status, so the sample `add 1 3` followed by `skip 2` cannot silently retarget a different row:

```text
  [1] Modal          greenhouse · 14 roles   fit 88
  [2] Baseten        ashby · 9 roles         fit 81
  [3] keyword        "inference serving"     new
```

`add <n…>` snapshots all selected proposal ids, then approves those ids sequentially; `skip <n> [reason]` dismisses one; `end` streams recap and exits; `quit` exits without ending; any other input becomes the next conversational message. Indexes are rebuilt from the current view after the complete command so an earlier approval cannot retarget a later number.

- [ ] **Step 4: Run CLI tests and commit**

Run: `.venv\Scripts\python.exe -m pytest tests/test_cli_scout.py tests/test_scout_service.py -q`

Expected: PASS.

```powershell
git add src/resume_agent/cli.py tests/test_cli_scout.py
git commit -m "feat: make scout cli conversational"
```

---

### Task 8: Retire backend duplication and regenerate contracts

**Files:**

- Modify: `src/resume_agent/api/routers/sources.py`
- Modify: `src/resume_agent/api/schemas/sources.py`
- Delete: the legacy backend modules/tests listed in File Structure
- Modify: `contracts/openapi.json`
- Modify: `contracts/ts/api.ts`
- Modify: `web/src/lib/api/schema.ts`

**Interfaces:**

- Consumes: all replacement backend coverage.
- Produces: one Scout API in OpenAPI; no `/api/sources/discover`, `/api/search/discover`, `DiscoverSourcesIn`, or `DiscoverSearchIn`.

- [ ] **Step 1: Add retirement assertions before deleting code**

In `tests/api/test_scout_router.py`, assert both legacy POSTs return 405: each literal path is still matched by a retained parameterized route for another method, but POST is no longer allowed. In `tests/api/test_openapi_contract.py`, assert the two legacy operations and schemas are absent while all ten Scout operations across nine paths are present.

- [ ] **Step 2: Remove legacy routes, schemas, modules, and superseded tests**

Keep `discovery/scout_models.py` unchanged. Before deletion, confirm every retained behavior has a replacement assertion: check-source exception JSON, seniority vocabulary, canonical URL/ATS dedupe, isolated validation, ranking, and prompt tool wiring.

- [ ] **Step 3: Run backend tests before contract generation**

Run: `.venv\Scripts\python.exe -m pytest tests/test_scout.py tests/test_scout_store.py tests/test_scout_context.py tests/test_scout_service.py tests/test_cli_scout.py tests/api/test_scout_router.py -q`

Expected: PASS with no imports of deleted modules.

- [ ] **Step 4: Regenerate OpenAPI and the TypeScript client**

Primary command:

```powershell
bash scripts/gen_ts_client.sh
```

If Git Bash rejects the CRLF wrapper at `set -euo pipefail`, run the equivalent Windows commands:

```powershell
.venv\Scripts\python.exe scripts\export_openapi.py
npx.cmd --yes openapi-typescript contracts/openapi.json -o contracts/ts/api.ts
Copy-Item -LiteralPath contracts\ts\api.ts -Destination web\src\lib\api\schema.ts -Force
```

- [ ] **Step 5: Run the drift gate and commit**

Run: `.venv\Scripts\python.exe -m pytest tests/api/test_openapi_contract.py -q`

Expected: PASS.

```powershell
git add src/resume_agent/api/routers/sources.py src/resume_agent/api/schemas/sources.py src/resume_agent/discovery src/resume_agent/services tests contracts/openapi.json contracts/ts/api.ts web/src/lib/api/schema.ts
git commit -m "refactor: retire one-shot scout flows"
```

---

### Task 9: Build the typed Scout query and mutation hooks

**Files:**

- Create: `web/src/features/scout/use-scout.ts`
- Create: `web/src/features/scout/use-scout.test.tsx`

**Interfaces:**

- Consumes: generated `components["schemas"]`, `api`, `unwrap`, run store/tracker, TanStack Query v5 object signatures.
- Produces: Scout type aliases and hooks for list/detail/start/message/end/approve/dismiss/archive/unarchive/delete.

- [ ] **Step 1: Write failing MSW hook tests**

Assert start sends `{ message }`, seeds a `scout-start` run, and invokes completion invalidation; detail is disabled for a null id; approve invalidates Scout detail/list plus `['sources']`; term approval also invalidates `['config', '/api/config/search']`; lifecycle mutations use exact paths; API errors surface through `toast.error`.

- [ ] **Step 2: Run the hook tests and verify failure**

Run: `npm.cmd --prefix web run test:run -- src/features/scout/use-scout.test.tsx`

Expected: FAIL because the hook module is missing.

- [ ] **Step 3: Implement generated-contract aliases and query keys**

```typescript
export type ScoutSession = components["schemas"]["ScoutSessionOut"];
export type ScoutSessionSummary = components["schemas"]["ScoutSessionSummaryOut"];
export type ScoutProposal = components["schemas"]["ScoutProposalOut"];

const scoutKeys = {
  all: ["scout-sessions"] as const,
  list: (includeArchived: boolean) => ["scout-sessions", includeArchived] as const,
  detail: (sessionId: string | null) => ["scout-session", sessionId] as const,
};
```

Use `useQuery({ queryKey, queryFn, enabled })`, `useMutation({ mutationFn, onSuccess, onError })`, and return the `Promise` from `invalidateQueries`/`Promise.all` so `isPending` remains true until visible data is fresh.

- [ ] **Step 4: Seed and track conversational runs**

Use one `seedScoutRun(run, onDone)` helper equivalent to the Coach implementation. Start/message/end hooks attach completion callbacks that invalidate list/detail and preserve the caller's callback for page-local state. Mutation hooks do not implement their own busy gate; the page checks query/run state before calling them.

- [ ] **Step 5: Run hook tests and commit**

Run: `npm.cmd --prefix web run test:run -- src/features/scout/use-scout.test.tsx`

Expected: PASS.

```powershell
git add web/src/features/scout/use-scout.ts web/src/features/scout/use-scout.test.tsx
git commit -m "feat: add scout web data hooks"
```

---

### Task 10: Build polished proposal cards and the proposal rail

**Files:**

- Create: `web/src/features/scout/ProposalCard.tsx`
- Create: `web/src/features/scout/ProposalCard.test.tsx`
- Create: `web/src/features/scout/ProposalRail.tsx`
- Create: `web/src/features/scout/ProposalRail.test.tsx`
- Modify: `web/src/index.css`

**Interfaces:**

- Consumes: `ScoutProposal`, approve/dismiss hooks, `scrapeAvailable`.
- Produces: `proposalLabel`, `proposalBadge`, `<ProposalCard>`, `<ProposalRail>`.

- [ ] **Step 1: Write failing card and rail tests**

Cover badge precedence exactly: `Added`, `Dismissed`, role count/`Validated`, `Scrape target`, `Already in sources`, `Avoid`, `Failed`, `New`. Assert Add is disabled for non-pending rows and `avoid`/`failed`/`duplicate`, unverified is disabled with the existing browser explanation when scraping is unavailable, citation anchors are HTTP(S) with `target="_blank" rel="noreferrer"`, the dismiss reason field is labeled and max-length 200, and resolved cards expose no active controls.

For the rail, make three validated approvals where the middle rejects; assert calls are sequential, cards one and three resolve, card two renders its error, and the batch continues.

- [ ] **Step 2: Run component tests and verify failure**

Run: `npm.cmd --prefix web run test:run -- src/features/scout/ProposalCard.test.tsx src/features/scout/ProposalRail.test.tsx`

Expected: FAIL because components are missing.

- [ ] **Step 3: Implement explicit badge and action rules**

```typescript
export function proposalBadge(row: ScoutProposal): string {
  if (row.status === "added") return "Added";
  if (row.status === "dismissed") return "Dismissed";
  if (row.check === "validated") {
    return row.source?.roleCount == null ? "Validated" : `${row.source.roleCount} roles`;
  }
  if (row.check === "unverified") return "Scrape target";
  if (row.check === "duplicate") return "Already in sources";
  if (row.check === "avoid") return "Avoid";
  if (row.check === "failed") return "Failed";
  return "New";
}
```

The card shows kind/company-or-term, ATS or term-kind secondary text, fit badge, reason, safe citations, durable dismissal reason, check error, and per-row mutation error. Dismiss expands an inline field instead of opening a modal; Escape collapses it and focus returns to the Dismiss button. Proposal actions rely on the repository's existing 150ms button press feedback and add no keydown-driven animation.

- [ ] **Step 4: Implement rail ordering and sequential batch approval**

Render pending proposals first in durable order, then resolved rows. “Add all validated” snapshots currently pending validated ids, loops with `await approve(id)`, captures each error in `Record<string, string>`, and never converts failures into successes. Disable the batch button while the loop is active and announce the final success/failure count through an `aria-live="polite"` status.

- [ ] **Step 5: Add restrained Scout state transitions**

```css
.scout-proposal-card {
  transition:
    border-color 160ms var(--ease-out-strong),
    background-color 160ms var(--ease-out-strong),
    opacity 160ms var(--ease-out-strong),
    transform 160ms var(--ease-out-strong);
}

@media (hover: hover) and (pointer: fine) {
  .scout-proposal-card[data-pending="true"]:hover {
    transform: translateY(-2px);
  }
}

@media (prefers-reduced-motion: reduce) {
  .scout-proposal-card { transition-property: border-color, background-color, opacity; }
  .scout-proposal-card[data-pending="true"]:hover { transform: none; }
}
```

Do not use `transition: all`, `ease-in`, scale-from-zero, keyframes for mutation states, or motion on Enter/Escape actions.

- [ ] **Step 6: Run component tests, axe checks, and commit**

Run: `npm.cmd --prefix web run test:run -- src/features/scout/ProposalCard.test.tsx src/features/scout/ProposalRail.test.tsx`

Expected: PASS, including `vitest-axe` assertions.

```powershell
git add web/src/features/scout/ProposalCard.tsx web/src/features/scout/ProposalCard.test.tsx web/src/features/scout/ProposalRail.tsx web/src/features/scout/ProposalRail.test.tsx web/src/index.css
git commit -m "feat: add scout proposal rail"
```

---

### Task 11: Build the responsive Scout conversation page

**Files:**

- Create: `web/src/features/scout/ScoutPage.tsx`
- Create: `web/src/features/scout/ScoutPage.test.tsx`

**Interfaces:**

- Consumes: Task 9 hooks, Task 10 rail, shared `ChatThread`, `ChatComposer`, `useChatStream`, run store.
- Produces: `<ScoutPage>` with first-turn, active, ended, error, stream-recovery, and session-history states.

- [ ] **Step 1: Write failing page workflow tests**

Test these user-visible paths with MSW and a fake EventSource:

- Empty page accepts a first message and attaches to the returned `scout-start` stream.
- A completed first run selects the new durable session and clears synthetic parts.
- An active session sends refinement with `turnCount`, shows reasoning/tool parts, and prevents duplicate sends while POST or stream is busy.
- Stop cancels, clears partial parts immediately, and leaves the durable transcript unchanged.
- Retry clears the failed partial and relaunches the last local message.
- Refresh attaches only to `scout-turn`/`scout-end` matching the displayed session; `scout-start` attaches before detail exists.
- End streams recap; ended sessions disable the composer but leave pending proposal actions enabled.
- The rail stacks below chat below `xl` and becomes a 22rem right column at `xl`.
- Session archive/unarchive/delete and archived filter preserve the same semantics as Coach history.
- The complete rendered page has no serious axe violations.

- [ ] **Step 2: Run the page tests and verify failure**

Run: `npm.cmd --prefix web run test:run -- src/features/scout/ScoutPage.test.tsx`

Expected: FAIL because `ScoutPage` is missing.

- [ ] **Step 3: Implement run attachment and synthetic-bubble lifecycle**

Use local `streamRunId`, `streamBaseline`, `suppressedRunId`, and `ignoredRuns` with the same cancellation invariants as Coach. Derive recovered runs from `useRunStore`:

```typescript
const recovered = Object.values(runs).find((run) =>
  ["scout-start", "scout-turn", "scout-end"].includes(run.kind) &&
  ["queued", "running", "cancelling"].includes(run.status) &&
  (run.kind === "scout-start" || run.meta?.sessionId === displayedSessionId)
);
```

For a start run with no durable session, render the locally entered user bubble when available plus streaming assistant parts, but do not query the missing session. Hide streaming parts synchronously when durable turn count exceeds the captured baseline.

- [ ] **Step 4: Implement the page layout and states**

Use a max-width workspace header (“Discovery Scout”), concise explanatory copy, End/New-session/actions controls, and this responsive structure:

```tsx
<div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
  <Card className="min-w-0 overflow-hidden">{/* ChatThread + ChatComposer */}</Card>
  <ProposalRail className="min-w-0 xl:sticky xl:top-24" />
</div>
```

The composer placeholder is “Ask for a change…” after session creation and a concrete discovery example in the empty state. Keep reasoning visible. Use existing alert, skeleton, empty, spinner, card, dropdown, and alert-dialog components; do not introduce a parallel component system.

- [ ] **Step 5: Implement durable transcript and history mapping**

Map each stored turn to a `ChatThreadMessage` with text plus notice. Proposal cards live in the rail, not inside messages; `proposalIds` remains available for future message linking. Past-session disclosure shows goal, turn excerpts, recap, and counts without enabling a composer. Delete requires confirmation; archive appears only for ended sessions.

- [ ] **Step 6: Run page and shared chat regression tests**

Run: `npm.cmd --prefix web run test:run -- src/features/scout/ScoutPage.test.tsx src/components/chat/ChatThread.test.tsx src/lib/chat/useChatStream.test.ts`

Expected: PASS.

```powershell
git add web/src/features/scout/ScoutPage.tsx web/src/features/scout/ScoutPage.test.tsx
git commit -m "feat: add discovery scout workspace"
```

---

### Task 12: Wire navigation and retire the old frontend dialogs

**Files:**

- Modify: `web/src/app/router.tsx`
- Modify: `web/src/app/AppLayout.tsx`
- Modify: `web/src/features/sources/SourcesPage.tsx`
- Modify: `web/src/features/sources/SourcesPage.test.tsx`
- Modify: `web/src/features/settings/pages/SearchSettingsPage.tsx`
- Delete: the legacy frontend files listed in File Structure

**Interfaces:**

- Consumes: `<ScoutPage>`.
- Produces: `/scout`, sidebar navigation, and “Ask the Scout” entry links from both previous discovery surfaces.

- [ ] **Step 1: Add failing navigation and entry-point assertions**

Assert Sources and Search settings render a link named “Ask the Scout” with `href="/scout"`; no old dialog trigger text remains. Add a router smoke assertion that the lazy Scout import resolves, and ensure sidebar active styling marks only `/scout` for the new item.

- [ ] **Step 2: Run the affected tests and verify failure**

Run: `npm.cmd --prefix web run test:run -- src/features/sources/SourcesPage.test.tsx src/features/settings/forms/SearchConfigForm.test.tsx src/features/scout/ScoutPage.test.tsx`

Expected: FAIL because navigation still targets legacy dialogs.

- [ ] **Step 3: Add the route and sidebar item**

Lazy-load `ScoutPage`, add `{ path: "scout", element: <SetupGate>{page(<ScoutPage />)}</SetupGate> }`, and add `{ to: "/scout", label: "Discovery Scout", icon: Compass }` at the start of “Find & tailor”. Preserve every existing route and sidebar item.

- [ ] **Step 4: Replace both dialog triggers with links and delete old files**

Use the Base UI single-interactive-element render pattern:

```tsx
<Button variant="outline" size="sm" render={<Link to="/scout" />}>
  <Sparkles data-icon="inline-start" aria-hidden="true" />
  Ask the Scout
</Button>
```

Remove dialog imports, draft-apply helpers that existed only for the modal, and the six old frontend files. Search the tree for their component/hook names and both legacy API paths; only historical docs may remain.

- [ ] **Step 5: Run frontend regression tests and commit**

Run: `npm.cmd --prefix web run test:run -- src/features/scout src/features/sources/SourcesPage.test.tsx src/features/settings`

Expected: PASS.

```powershell
git add web/src/app web/src/features/scout web/src/features/sources web/src/features/settings web/src/features/search-scout
git commit -m "refactor: route discovery through the scout"
```

---

### Task 13: Complete cross-layer verification and manual interaction review

**Files:**

- Verify all changed files; modify only defects discovered by these checks.

**Interfaces:**

- Consumes: the complete feature.
- Produces: evidence that domain, API, CLI, generated contracts, UI, accessibility, retirement, and repository-wide behavior agree.

- [ ] **Step 1: Run static retirement and contract searches**

```powershell
rg -n "source_scout|search_scout|source_discovery|search_discovery|DiscoverCompaniesDialog|SuggestSearchTermsDialog|/api/sources/discover|/api/search/discover|source-scout-research|search-scout-research" src tests web/src contracts
```

Expected: no live-code hits. Generated contracts contain `/api/scout/sessions`, `ScoutProposalOut`, and `ScoutSessionOut` exactly once per schema/path definition.

- [ ] **Step 2: Run focused Python and API verification**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_scout.py tests/test_scout_store.py tests/test_scout_context.py tests/test_scout_service.py tests/test_cli_scout.py tests/test_prompt_registry.py tests/api/test_scout_router.py tests/api/test_openapi_contract.py -q
```

Expected: PASS.

- [ ] **Step 3: Run focused web verification**

```powershell
npm.cmd --prefix web run test:run -- src/features/scout src/features/sources/SourcesPage.test.tsx src/components/chat src/lib/chat
```

Expected: PASS.

- [ ] **Step 4: Run the full repository gates**

```powershell
.venv\Scripts\python.exe -m ruff check src tests evals
.venv\Scripts\python.exe -m pytest tests -q
npm.cmd --prefix web run lint
npm.cmd --prefix web run test:run
npm.cmd --prefix web run build
git diff --check
```

Expected: every command completes successfully. A timeout is reported as incomplete verification, never as a pass.

- [ ] **Step 5: Perform a manual browser and keyboard review**

Run `make dev`, then verify: first-turn streaming; web-search and `check_source` chips resolve in arrival order; refinement preserves transcript and ledger; Stop leaves no durable turn; retry replaces partial output; Add and Dismiss update badges without layout jump; Add-all continues after one failure; ended sessions still allow pending actions; refresh reattaches to the correct run; Sources/Search links open `/scout`; mobile stacking works at 375px; keyboard focus order is transcript → proposal actions → composer; Escape closes dismiss input; reduced-motion removes card movement.

- [ ] **Step 6: Inspect motion in slow mode and commit fixes**

Use Chrome DevTools Animations at 4× slowdown. Confirm card state transitions start immediately, finish within 200ms, animate only transform/opacity/color/border, do not restart on rapid status changes, and never animate keyboard-triggered send/stop actions. Correct any defect and rerun the affected Vitest file plus lint.

- [ ] **Step 7: Commit verification fixes, if any**

```powershell
git add src tests web contracts
git commit -m "test: verify conversational discovery scout"
```

If verification required no changes, do not create an empty commit.

---

## Self-Review

### Spec coverage

| Design requirement | Tasks |
| --- | --- |
| Consolidated Scout persona and formatter | 1 |
| Strict session/proposal model and one-active lifecycle | 2 |
| Standing goal, transcript elision, feedback ledger | 3 |
| Streaming prose/tool activity, blocking fallback, cancellation | 4 |
| Config + session dedupe and concurrent isolated probes | 3, 4 |
| Validation structural/integrity split with durable notices | 1, 4 |
| 8-per-turn and 40-pending caps | 1, 2, 4 |
| Human-only source/search writes and bounded lock semantics | 5 |
| Approval after end; message rejection after end | 2, 5, 6 |
| Full HTTP lifecycle and refresh metadata | 6 |
| Conversational CLI on identical services | 7 |
| Legacy route/module/prompt retirement | 8 |
| OpenAPI/TypeScript regeneration | 8 |
| Typed React Query hooks | 9 |
| Proposal badge/action semantics and Add-all | 10 |
| Shared chat primitives, stop/retry/recovery/reasoning | 11 |
| Responsive, accessible, reduced-motion frontend | 10, 11, 13 |
| Sidebar and Sources/Search entry points | 12 |
| Offline and full-repository verification | every task, 13 |

No uncovered design requirement remains.

### Placeholder scan

The plan contains no deferred implementation markers, vague error-handling directions, or references to undefined neighboring interfaces. Every task names concrete files, signatures, assertions, commands, expected outcomes, and commit boundaries.

### Type consistency

- Domain `kind` is `source | search_term`; wire output uses the same values.
- Formatter-only `disposition` becomes stored `check`; it never crosses the API.
- Stored checks are exactly `validated | unverified | failed | duplicate | avoid | new`; statuses are exactly `pending | added | dismissed` in Python, OpenAPI, and TypeScript.
- `term_kind` and `_EXISTING_FIELD` use the same seven-value vocabulary.
- Proposal ids are generated only by `scout_store` and are called `proposal_id` in Python route parameters and `proposalId` on the wire.
- Run kinds and metadata are identical in router, hooks, page recovery, and tests.
- `scrapeAvailable` is computed in session views and consumed by card gating; it is absent from stored JSON.

### Current documentation checks applied

- FastAPI response models and typed dependencies remain the serialization/validation boundary; 202 launch and 204 delete status codes are declared on path operations.
- Pydantic v2 after-validators return `Self`, list fields use `default_factory`, and persisted objects round-trip through `model_validate` plus `model_dump(mode="json")`.
- TanStack Query v5 hooks use the object signature; successful mutations return awaited invalidation promises; composed batch actions use `mutateAsync` and explicit application-level gating.
