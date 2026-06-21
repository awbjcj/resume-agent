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
company, title, location, jd_text, posted_at.
_Avoid_: posting, listing, record

**Host identity**:
A URL's ATS resolved by host and path alone, with no network — `identify_host`.
`detect_ats` is host identity first, then an L2 HTML sniff for embedded ATSes.
url_ingest uses host identity on a page it already holds, so the sniff never
re-fetches it.
_Avoid_: detection (reserve for the full `detect_ats`, sniff included)

**Posting reader**:
A `reader(html) -> ExtractedJob` for one ATS's single posting page, registered in
url_ingest's `_READERS` by host identity. The single-posting counterpart to a
Producer (which maps a board's whole list). LinkedIn has one but stays off the
registry — it is a scraper target, not an ATS.
_Avoid_: parser, scraper, extractor

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
