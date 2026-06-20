# Resume Agent — Domain Language

Shared vocabulary for the resume agent, so code, tests, and architecture
discussion name the same concepts the same way. Architecture terms
(module, interface, seam, deep/shallow) follow their usual meaning; this file
records the **domain** nouns specific to this project.

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

**RelevanceGate**:
The title-and-JD filter applied to the harvested union; `title_relevance_gate`
is its title-only form used before JD text is available (Workday/Tesla list rows).
_Avoid_: filter (filtering is a later pipeline stage on persisted jobs)
