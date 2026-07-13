# Resume Agent — Domain Language

Shared vocabulary for the resume agent, so code, tests, and architecture
discussion name the same concepts the same way. Architecture terms
(module, interface, seam, deep/shallow) follow their usual meaning; this file
records the **domain** nouns specific to this project.

## LLM providers

**Model seam** (`build_model`):
The single constructor every agent builder calls to turn a model id into an agno
model. The only code that knows about provider SDKs; builders never import a
concrete model class. Lazy per-branch imports keep unused provider SDKs unloaded.
_Avoid_: model factory loop, client builder (it builds one model, not a client)

**Provider-prefixed model id**:
A model id of the form `provider:model` (`openai:`, `gemini:`, `deepseek:`); a
bare id, or an unknown prefix, is Anthropic. `split_provider` parses it,
`resolve_api_key` maps the provider to its configured key. Lets tiers mix
providers without a separate provider setting.
_Avoid_: namespaced model, qualified id (reserve "provider" for the prefix value)

## Discovery & connectors

**Connector**:
A job source behind the shared `fetch` seam — it returns a `FetchResult` for a
`SearchConfig`. Greenhouse, Lever, Companies, Adzuna, RemoteOK, LinkedIn.
_Avoid_: provider, plugin, scraper (a scraper is one kind of connector)

**Unit**:
The thing a connector fans out over — a Greenhouse board, a careers URL. The
per-iteration item a `Harvest` walks.
_Avoid_: source (a source is the connector), item, entry

**Producer**:
A connector's `unit -> list[RawJob]` function: how one Unit becomes jobs. The
genuine per-connector variation that stays outside the `Harvest` seam.
_Avoid_: parser (parsing is only part of producing), handler, callback

**Harvest**:
The deep seam that fans out over a connector's Units, isolates each Unit's
failure, then gates and caps the union. Owns iteration, failure isolation, the
relevance gate, the filtered count, and the limit — everything five connectors
used to copy. Single-call connectors reuse only its tail via `gate_and_limit`.
_Avoid_: fetch loop, pull loop, runner (the runner orchestrates connectors;
a harvest is internal to one connector)

**Detailed harvest**:
The N+1 variant of Harvest for boards that list titles then serve each JD on a
separate detail endpoint (Workday, Tesla): title-gate each row, fetch its detail,
apply it, then run the full relevance gate. One stale detail endpoint skips its
row, not the batch. `harvest_detailed`.
_Avoid_: N+1 loop, detail loop

**FetchResult**:
What a connector's `fetch` returns: `jobs`, `failures` (Unit key → reason), and
`filtered` (count dropped by the relevance gate). Replaces the duck-typed
`.filtered` / `.failures` attributes the runner used to read off the instance.
_Avoid_: response, payload, output

**Failure** (connector):
A single Unit skipped during a Harvest, recorded as `key -> reason` instead of
aborting the run. A bad board token, an undetected ATS, a parse error on a
reverse-engineered payload.
_Avoid_: error (an error aborts; a failure is isolated and recorded)

**RawJob**:
A single opening as a connector emits it, ready for ingest — source, url,
company, title, location, jd*text, posted_at.
\_Avoid*: posting, listing, record

**Host identity**:
A URL's ATS resolved by host and path alone, with no network — `identify_host`.
`detect_ats` is host identity first, then an L2 HTML sniff for embedded ATSes.
url*ingest uses host identity on a page it already holds, so the sniff never
re-fetches it.
\_Avoid*: detection (reserve for the full `detect_ats`, sniff included)

**Posting reader**:
A `reader(html) -> ExtractedJob` for one ATS's single posting page, registered in
url*ingest's `_READERS` by host identity. The single-posting counterpart to a
Producer (which maps a board's whole list). LinkedIn has one but stays off the
registry — it is a scraper target, not an ATS.
\_Avoid*: parser, scraper, extractor

**RelevanceGate**:
The title-and-JD filter applied to the harvested union; `title_relevance_gate`
is its title-only form used before JD text is available (Workday/Tesla list rows).
_Avoid_: filter (filtering is a later pipeline stage on persisted jobs)

## Tailoring & verdict

**Verdict**:
What one tailoring round earns — `PanelVerdict`: `gate_passed`, `aggregate_score`,
`passed`, and the `critiques` behind them. Built by exactly one constructor,
`aggregate`, so "what makes a round pass" has a single shape.
_Avoid_: result, outcome, score (the score is one field of the verdict)

**Gate critique**:
A `ReviewCritique` whose `passed` blocks the round regardless of score — the
configured gate reviewers (LLM fact-check) plus the deterministic gates. The
fact-lock invariant rides here, not in a separate bool.
_Avoid_: hard gate (the gate is the policy; this is one critique that carries it)

**Deterministic gate**:
A gate decided in-process without an LLM — provenance: every cited id must
resolve to a real fact. Emitted as a gate critique by `provenance_critique`, it
guards the expensive panel: when it fails the round, the workflow skips the LLM
reviewers. `DETERMINISTIC_GATES` in `verdict.py` names the set; `aggregate`
gates on it alongside the configured reviewer gates.
_Avoid_: pre-check, structural check (it is a first-class gate, not a precondition)

## Ingest & source priority

**IncomingJob**:
A job offered to ingest, normalized — strings trimmed, blanks collapsed to None.
Built once from a connector's RawJob or the manual/URL kwargs.
_Avoid_: candidate, payload

**Merge decision**:
The pure rule, given the matched row and an IncomingJob, for what wins —
canonical beats aggregator, a tailored posting's text is frozen, raw rows
re-base and merge optionals without erasing. `decide`, returning a MergeAction.
Distinct from matching (`find_existing`), which is DB-bound.
_Avoid_: dedupe (dedupe is the key + the match; this is the post-match policy)

**MergeAction**:
The typed result of the Merge decision, carrying the writes the applier performs:
`Insert`, `Skip`, `UpgradeUrlOnly`, `Rebase`. The applier holds no policy.
_Avoid_: outcome (reserve IngestOutcome for the inserted/upgraded/skipped tag)

**Location guard**:
The location-compatibility check inside matching (`find_existing`): a candidate
row only matches when `locations_compatible` holds — blank on either side is a
wildcard; otherwise the normalized city segments (text before the first comma)
must be token-subset-related. Guards the identical-JD, dedup_key, and
keyless-fingerprint branches; never the URL branch. Splits multi-location
same-title reqs into sibling rows without changing `compute_dedup_key`.
_Avoid_: location filter (filtering is a pipeline stage), dedupe rule (the key
is unchanged; this guards the match)

## Runs & skill classification

**Run snapshot**:
The validated in-memory view of one file-backed background run. Its id comes from
the requested id/file stem; kind, state, counters, and timestamps must validate
before the snapshot crosses the RunManager seam. Raw progress dictionaries stay
inside the run substrate.
_Avoid_: run record (that names the persistence shape), progress payload

**Skill classification**:
The incremental operation that maps newly demanded skill tokens to stable
canonicals, reconciles new heads across batches, and assigns stable theme ids. It
owns batching, model-output projection, retryable failures, progress, and metrics
behind one module interface.
_Avoid_: clustering pipeline (classification includes retry and theme identity),
canonicalize service

**Classification backlog**:
Demanded work not yet present in the Cluster map: a token missing from `aliases`,
or a demanded canonical missing from `theme_of`. Absence is intentional retry
state; identity aliases and `Other` themes are successful classifications only
when explicitly accepted, never failure placeholders.
_Avoid_: delta (the alias delta is only one half of the backlog), failed cache

**Cluster map**:
The atomically persisted aliases, canonical-to-theme assignments, and stable theme
labels used by the Match-gap demand graph. Existing terminal canonicals and theme
ids are stable choices; incremental additions may point to them but do not rewrite
them.
_Avoid_: taxonomy cache, classification result

## Profile corpus

**Fragment cache walk**:
The deep seam over the source manifest that owns per-document caching -- sha
check, manifest bump, meta match, cache hit, error -> stale fallback, atomic
save, and the status vocabulary (`cached` / `extracted` / `source-changed` /
`stale:` / `failed:`). `_walk_fragments`; both extraction modes run through it.
_Avoid_: extraction loop, cache layer

**Fragment producer**:
One extraction mode behind the Fragment cache walk: which docs it selects, the
meta dict that keys their cache entries, and the async produce step
(doc, text -> Produced). The profile-corpus counterpart of a discovery Producer
-- the genuine per-mode variation that stays outside the walk.
_Avoid_: extractor (reserve for the literal-mode agent), handler

**Produced fragment**:
What a Fragment producer yields for one document: the fragment's `facts`, an
optional `evidence` sidecar (synthesis only), and optional verification `drops`.
`Produced` in `profile/fragments.py`.
_Avoid_: extraction result, payload

## Deployment & data custody

**Data root**:
The single mutable filesystem tree an instance owns — `system.db` plus every
user's Workspace under `users/`. The unit of custody: export and import move
it whole, never a slice. Exactly one instance is authoritative for a data
root at a time (the deployed instance, once one exists).
_Avoid_: data dir (that names a path, not the custody unit)

**Workspace**:
One user's tree under `users/<user_id>/` inside the Data root — their jobs DB,
profile corpus, mutable config, operational secrets, renders, and run logs.
The unit of tenancy isolation (by file, never by row); a UserContext binds a
request or CLI invocation to exactly one Workspace.
_Avoid_: user data root (custody belongs to the Data root, not the slice),
home dir

**Round-trip pull**:
The sanctioned path for browser-requiring connectors once the cloud instance
owns the Data root: export, run the local browser pull against the snapshot,
import it back — without mutating the cloud in between. Admins round-trip the
whole Data root; a user round-trips their own slice via Workspace export.
Re-pulls are safe because ingest dedupe makes equal-tier duplicates no-ops.
_Avoid_: sync (nothing merges; a whole custody unit moves), hybrid pull

**Workspace export**:
User-content portability of exactly one Workspace — the archive of a user's
slice, exportable and importable by that user without admin custody ever
changing hands. Distinct from Data root export: it carries no system tables
and claims no authority over the instance; importing one replaces only the
caller's Workspace, staged and rollback-safe, refused while the caller has an
active run. Because a Workspace holds Operational secrets, the archive is
secret material.
_Avoid_: self-export (names the actor, not the unit), backup (a backup is the
Data root), partial export (it is complete for its Workspace)

**UserContext**:
The binding of one authenticated user to their Workspace and effective
settings for the duration of exactly one request, background run, or CLI
invocation. The unit the tenancy seam passes around; nothing user-scoped is
resolved outside one.
_Avoid_: session (a session is one way a UserContext gets established), tenant

**Budget**:
A user's rolling 7-day weighted-token allowance against the shared provider
keys. Recorded always; enforced only for non-admin users on shared keys, and
checked when a phase starts, not per call.
_Avoid_: quota (quotas cap resources, budgets cap spend), token limit

**Quota**:
A per-user resource cap that applies to everyone regardless of key or role —
active-job count, concurrent runs. Protects the shared instance, not the bill.
_Avoid_: budget, rate limit (rate limiting is auth brute-force protection)

**Personal access token (PAT)**:
A long-lived, revocable, role-equivalent bearer secret a user mints for
scripting the API; shown once, stored hashed, header-only. The PAT *is* the
user.
_Avoid_: API token (that named the removed static shared secret), key

**Link token**:
A short-lived signed token carried in a query param for surfaces that cannot
send headers (SSE, downloads); scoped to a user and a purpose.
_Avoid_: query token, download token (purpose-specific names hide the concept)

**Invite code**:
A single-use, expiring, role-less registration secret minted by an admin;
consuming it is the only way to create an account.
_Avoid_: invitation link (it is a code, not a URL), signup token

**Platform secret**:
Configuration the app cannot manage for itself because it gates getting in or
booting at all — the first-admin seed credentials (read once, then inert),
the session signing key, capability flags. Lives with the platform
(deploy-time env), never in the Data root, so it survives a root replace and
cannot be locked away by the thing it unlocks.
_Avoid_: system secret, infra config

**Operational secret**:
A credential the app spends while doing its work — LLM provider keys, GitHub
token, Adzuna keys, LinkedIn login. Managed through the web Secrets page,
stored in the Data root, and therefore travels with an export: a backup of the
root is itself secret material.
_Avoid_: app secret (too close to Platform secret to scan well), API key (one
kind, not the category)

## Board & shortlist filtering

**Board seam**:
`services/board` — the single place board-data _policy_ and _assembled reads_
live. Owns the mutations (`set_stage`, `set_archived`, `delete`,
`upsert_application`) and the assembled detail read (`get_job_detail`). Raw list
projections (`shortlist_rows`, `pipeline_rows`, `triage_rows`) stay in
`tracking.queries` and are called directly by both adapters — wrapping them in
board would add shallow pass-throughs and fight the frontend's rich in-process
filtering. Adapters cross this seam for mutations; they never re-import
`tracking.repository` mutation functions. Bulk actions are transactional: one
batched load plus `progressed_job_ids` gate, then one commit; `delete_job_row` is
the unguarded cascade shared with `delete_job` and prune.
_Avoid_: board service (it is the seam, not a layer), repository (the repository
is what board guards)

**JobDetailRow**:
The flat read-model for one job's detail view, assembled by `job_detail_row`
(reusing `_shortlist_row` for the facet half). Field-named to match the
`JobDetail` API schema exactly, so the router projects it in one
`JobDetail.model_validate(row)` — no hand-mapping. The detail counterpart to
`ShortlistRow`.
_Avoid_: detail DTO, job view (name it for the row it is)

**Filter contract**:
The cross-language behavioral spec for shortlist filter-and-rank: a checked-in
fixture of `(rows, filterState) -> ordered [job id]` cases, rows in the camelCase
`ShortlistItem` wire shape. It is the single interface for a predicate that
genuinely runs in two runtimes — `services/shortlist_filtering.py` (Python) and
`web/src/lib/filters` (React, TS). Both implementations stay; the contract is the
one thing that cannot drift. Lives in `contracts/` beside `openapi.json`.
_Avoid_: filter test, fixture (it is the interface, not one side's test)

**Conformance harness**:
The thin per-runtime runner that feeds the Filter contract through one
implementation and asserts the ordered ids — pytest through `filtering.py`, vitest
through `apply.ts`/`sort.ts`. Owns no behavior; only proves an adapter satisfies
the contract. Language-local edge cases (None vs undefined, tz-naive dates) stay in
ordinary unit tests; shared behavior lives in the contract.
_Avoid_: unit test (a conformance harness asserts the shared contract, not
language-local edges)

**Composite rank**:
The weighted fit/salary/recency sort key (`PRESETS`) for the shortlist. Sorted at
full precision so Python and JS order identically — the `round`/`Math.round` step
is display-only and never enters the ordering. The Filter contract pins this.
_Avoid_: composite score (the score is the value; the rank is its use as sort key)
