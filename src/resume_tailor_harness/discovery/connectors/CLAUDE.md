# Discovery connectors — developer reference

Migrated from the project root `CLAUDE.md` (2026-08-02, /doctor lazy-load pass) — loads only when working under `src/resume_tailor_harness/discovery/connectors/`.

## ATS detection flow (`detect.py`)

`detect_ats(url)` resolves in order — stop at the first match:

1. **Singleton host match** — `tesla.com/careers` → `AtsTarget("tesla")`;
   `careers.google.com` → `AtsTarget("google")`. No token; the host is the
   identity. Checked before L1/L2.
2. **L1 URL pattern** — host + path directly reveals ATS and board token
   (Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee, Personio,
   Breezy, JazzHR, BambooHR, and the Workday triple from
   `{tenant}.{dc}.myworkdayjobs.com/{site}`).
3. **L2 HTML sniff** — fetches the page, scans for embedded ATS markers
   (Greenhouse embed `?for=`, Lever/Ashby slugs, Workday full URL in HTML).

`AtsTarget` fields: `ats`, `token` (single-slug ATS account), `country` (Personio
host suffix), `tenant` +
`datacenter` + `site` (Workday triple). Tesla/Google carry only `ats`.

---

## Single-URL ATS readers (`url_ingest/ats_readers.py`)

Add-from-URL routes a pasted posting through `identify_host` (pure, no network)
to a deterministic reader — the browser is never used for a recognized ATS.

- **The ATS's own JSON API is tried first; the page's JSON-LD is the fallback.**
  A posting page shows more than its body: location, workplace type, employment
  type, department, and compensation live in a sidebar or top bar that the API
  exposes as dedicated fields. schema.org `JobPosting` markup carries only a
  subset and many boards emit none of it, so preferring JSON-LD because it is
  free silently dropped exactly the facts this module exists to capture. The
  API result wins whenever it resolves; JSON-LD fills blank fields and takes
  over entirely when the API cannot resolve the job. `_prefer(*candidates)`
  owns that rule — first candidate with a `jd_text` wins, the rest fill its gaps.
- **Sidebar facts ride in `jd_text` as `Label: value` lines** (the shape
  `ashby.parse_ashby` already used), so the relevance gate, criteria
  extraction, and tailoring read them as part of the description.
  `_json_ld_meta_lines` renders the schema.org equivalents — `baseSalary`,
  `employmentType`, `jobLocationType`, `occupationalCategory` — which the
  4-field description-only mapping used to discard.
- **The page's JSON-LD enriches whatever produced the body, via
  `with_json_ld_meta` — `_prefer` cannot do this.** `_prefer` merges only
  _scalar_ fields, so the candidate that wins on `jd_text` keeps its own meta
  lines and every other candidate's are dropped. `service.job_from_url`
  therefore runs `with_json_ld_meta` over **both** branches — the reader result
  and the LLM result — adding only labels the body does not already carry, so a
  reader that renders its own sidebar is unchanged and the pass is idempotent.
  Two cases need it. Greenhouse's board API carries the description but none of
  the pay band or employment type (measured on Stripe's board: the job API
  returns `location: {"name": "N/A"}` and no compensation, while the page's
  JSON-LD carries Toronto / `FULL_TIME` / CAD 135,200–258,000). And an
  **employer-hosted posting is not a detectable ATS at all** — `stripe.com`
  links Greenhouse only as a `greenhouseId` inside `__NEXT_DATA__`, never as a
  `boards.greenhouse.io` URL, so the L2 sniff correctly declines it.
  `read_employer_hosted_greenhouse` recognizes that structured listing and
  reads its server-rendered semantic body blocks before the LLM fallback. This
  preserves Stripe's page-only "In-office expectations" and "Pay and
  benefits" sections, while the listing data and JSON-LD supply location,
  employment type, and compensation. Routing such a URL to the Greenhouse API
  would be a regression because its body omits those employer-owned sections.
  The normal Greenhouse board connector applies the same employer-page reader
  to its kept employer-hosted rows after relevance gating, known-row filtering,
  and the per-board cap. This covers source pulls as well as pasted URLs without
  issuing an extra page request for every role on a large board.
- **A reader returns `None`, never an `ExtractedJob` with an empty `jd_text`.**
  That is the contract `service.job_from_url` keys its LLM fallback on; an
  empty-but-present result suppresses the fallback and fails the ingest even
  though the JD is sitting in the static HTML. `_api()` converts every lookup
  failure to `None`, and it catches `ValueError` as well as `httpx.HTTPError`
  because a maintenance page or bot interstitial served with status `200`
  raises out of `.json()`, not out of the transport.
- **Two host kinds are still browser-eligible:** an unrecognized one, and a
  `detect.SINGLETON_ATS` portal (Tesla, Google Careers), which is recognized by
  host but builds its listings in JavaScript — static HTML holds nothing for
  either a reader or the LLM. Both reuse the already-fetched page via
  `fetch.upgrade_if_shell` rather than issuing a second request for it.
- **Routing reads the post-redirect `final_url`**, so a tracking or shortened
  link that lands on LinkedIn still reaches `read_linkedin_posting`.
- Workday goes through `workday.fetch_job_detail` (not a bare `httpx.get`) so a
  pasted URL inherits the same 429/5xx retry a board pull gets, and stores
  `jobPostingInfo.companyName` rather than the tenant slug — a slug as the
  company breaks `dedup_key` against the same requisition pulled from the board.

---

## Companies connector dispatch (`companies.py`)

`CompaniesConnector.fetch` delegates to the `harvest` seam: for each URL in
`self.urls` it calls `detect_ats`, looks up the backend in `_BACKENDS`, and calls
`backend(target, search, effective_limit, skip_seen)`. Each `CompanyUrl.limit`
overrides the global per-unit fallback. Any URL that fails detection or whose backend
raises `httpx.HTTPError` / a parse error is recorded on the returned
`FetchResult.failures` (url → reason) — it never aborts the run. The relevance
gate and cap run per URL; the union is not capped, so one prolific board cannot
consume another URL's budget.

To add a new backend: write `fetch_<name>(target, search, limit, skip_seen=None) -> list[RawJob]`
in a new module, add detection logic to `detect.py`, register in `_BACKENDS`.
Connector construction itself is table-driven: `CONNECTOR_SPECS` in `registry.py` is the
single enumeration of connector kinds; adding an ATS appends one `ConnectorSpec`.
Source Manager CRUD (`services/sources.py`) rides that same table: `ConnectorSpec`'s
unit-addressing half (`section`/`unit_items`/`admits`/`new_unit`) plus `find_unit`/
`spec_for` mean enable/limit/remove/add walk the specs instead of hand-enumerating kinds.

---

## Board-level sidebar lines (`greenhouse.py`, `lever.py`, `ashby.py`)

A board connector owes `jd_text` the same `Label: value` header the single-URL
readers render — the board API returns those facts as dedicated fields, not
inside `content`, so mapping only the description drops them. `parse_greenhouse`
was doing exactly that: measured across two workspaces, **0 of 1,159** stored
greenhouse rows carried a `Location:` / `Employment Type:` / `Compensation:`
line, against 561/561 for ashby. It now emits Location, Workplace Type, and
Department (live: anthropic 441/441 · 389/441 · 441/441; stripe 555/578 · 0 ·
578/578; figma 161/161 · 0 · 161/161).

Two Greenhouse-specific traps:

- **`location.name` is the literal string `"N/A"` when unset** — a value, not
  an absent key (23 of Stripe's 578 jobs). It is suppressed, not rendered.
- **Composite `location.name` values can repeat the same cities across `;` and
  `|` groups.** Normalize only when duplicates are present, preserving the
  first-seen order (live Anthropic example: SF / NYC repeated before Seattle).
- **`metadata` is per-board custom fields, not an API enum.** Only names known
  to carry a sidebar fact are mapped (`_METADATA_LABELS`); a blanket
  passthrough would write a board's internal bookkeeping (req owner, budget
  code) into the JD. Anthropic's "Location Type" is the workplace-type field;
  Stripe and Figma set no metadata at all, and an unanswered field has
  `value: null`.

**Every board connector now renders this header** — the four that did not
(`workable`, `recruitee`, `personio`, `workday`) plus the three JSON-LD ones
(`breezy`, `jazzhr`, `bamboohr`) were mapping only the description body. The
join lives once in `text.with_meta_lines`, and `text.jobposting_meta_lines`
(moved out of `url_ingest/ats_readers.py`, which could not be imported from here
without a cycle) renders the schema.org equivalents for the JSON-LD connectors.
Measured drops: Workable lost employment type / experience / education /
department / industry and the `telecommuting` flag, which is the only statement
of its remote policy; Recruitee lost the pay band plus experience, education and
its three placement booleans; Personio lost employment type, seniority, schedule
and department; Workday lost `timeType` and `remoteType`, neither of which
appears anywhere in `jobDescription`.

**A provider's free-text location field may not name a place at all.**
`recruitee`'s `location` is employer-typed and is very often a *status* —
"Remote job" on **5 of 6** postings on one live board — which resolves to no
city, region or country whatsoever, while `city` / `state_name` / `country` and
the `locations` array carried all three. Structured fields win there; the label
is only the fallback. `personio`'s `office` scalar has the sibling problem: it
joins offices with a bare comma and no space ("Madrid,Madrid (Remote)"), which
reads as one "City, Region" pair, so the `offices` array is used instead (7 of 9
postings on one board carry more than one).

**`ashby` completes its location from `address.postalAddress`, and only ever
fills gaps.** Ashby's `location` is frequently a bare city, which strands the
taxonomy with no country — and an unresolved country drops the region too, so
**577 of 758** OpenAI rows carried neither (0 after). The address is safe to use
because it is *job-specific*: it tracks `location` one-to-one across 22 distinct
values, and remote rows correctly carry no locality. It must never *replace* the
employer's own text, for three separate reasons, each pinned by a test — an
already-comma-structured label ("London, UK") gets its real city pushed out of
the city slot; a multi-place label ("United States & Canada") would be pinned to
one office; and a label that is itself a country ("Singapore") would be doubled.
Provider data quality is the other reason: Ramp writes "San Fransisco" and a
region of "Sweden" for Sweden.

**Greenhouse's `offices[]` is the counter-example — do not adopt it.** It looks
like the same upgrade (`offices[0].location` is the tidy "Ann Arbor, Michigan,
United States" against a `location.name` of "Ann Arbor, MI - Hybrid") and on
maymobility it "resolves better" for 14 of 44 rows. But those 14 are exactly the
`USA - Remote` rows, where `offices[]` is the org's HQ: adopting it would pin a
remote job to a city it is not in. Unlike Ashby's `address`, `offices[]` is an
organization-level list, not a per-posting one.

`smartrecruiters.apply_detail` had the same gap and now renders Location,
Employment Type, Experience Level, Department and Industry through the shared
`text.with_meta_lines`. Its location comes from **`location.fullLocation`**, not
a hand-join of the parts: SmartRecruiters ships that field on every posting
(measured 100/100 on one board, on both the list and detail endpoints) and
spells the country out, where the sibling `country` key is a *lowercase* alpha-2
code. Joining the parts fed the taxonomy "Colombo, Western Province, lk" — a
strictly poorer input than the string the provider already rendered. The join
survives only as a fallback, with the code upper-cased.

`parse_lever` had the same gap (0/133 rows) and now emits Location (with
`allLocations` extras as `(also: …)`), Workplace Type, Employment Type
(`categories.commitment`), Department (`department (team)`), Level, and
Compensation from the structured `salaryRange`. Live: zoox 244/244 · 244/244 ·
237/244 · 244/244 · 235/244; matchgroup 84/84 · 84/84 · 79/84 · 84/84 · 51/84.
`workplaceType` arrives lowercase (`hybrid`, `onsite`) and is capitalized.

**Lever also has a second, larger loss: `salaryDescription`.** `_assemble_jd`
read only `description`/`lists`/`additional`, so the pay-and-benefits _prose_
was dropped whole — 212 of zoox's 244 postings carry one, and **none** of those
texts appear anywhere in the other three fields, so this was not a duplicate.
It is now joined before `additional`, keeping the closing boilerplate last as
the page renders it.

---

## Workday N+1 pattern (`workday.py`)

Workday boards can have thousands of global listings — pulling all then gating
locally is infeasible.

1. **POST** `…/wday/cxs/{tenant}/{site}/jobs` with `{"searchText": ..., "limit": 20, "offset": N, "appliedFacets": ...}` — paginated list, title + location only. Location facets are tenant-resolved and cached when every configured location matches; misses stay unfaceted.
   - **Location facets are sent when safely resolvable.** The first plain page's
     location facet descriptors are matched case-insensitively against every
     configured `search.yaml` location, then cached under
     `data/workday_facets/{tenant}-{site}.json`. Partial/malformed matches,
     cache failures, and empty faceted restarts fall back to searchText-only
     paging. Category/job-family facets remain out of scope.
2. **`title_relevance_gate`** prunes the list _before_ any detail fetch.
3. **GET** `…/wday/cxs/{tenant}/{site}{externalPath}` for each survivor → `jobPostingInfo.jobDescription` (HTML → text via `html_to_text`).

**The employer name is not where the docs say it is — read it via
`detail_company_name(detail)`, never `jobPostingInfo.companyName`.** Workday now
serves that documented key as `null`: measured live on four unrelated tenants
(generalmotors, phinia, toyota, nvidia) it was null on every one, with the real
name at the payload's **top level** under `hiringOrganization.name`. Note the
helper takes the _whole_ detail payload, not `jobPostingInfo`.

This drift was silent and cost two things. Every row kept the URL slug as its
company with `company_provenance == "token"` — the slug-as-company case
`dedup_key` cannot reconcile. And because Scout's board verification proves
ownership from provider-attributed company names
(`services/sources.py::preview_source` collects `observed_companies` from rows
whose provenance is `provider`), **no Workday board could verify at all**:
`observed_companies` was always empty, so even
`generalmotors.wd5.myworkdayjobs.com` came back `OWNERSHIP_NOT_PROVEN`. It now
resolves `VERIFIED_PROVIDER_METADATA`, while a mismatched pair (Ford vs the GM
board) still returns `ATS_CONFLICT`.

The names are legal entities, not trade names — "2100 NVIDIA USA", "PHINIA
Delphi India Private Limited - (India)". `identity.company_names_match` is what
absorbs that (legal-suffix stripping plus a subset rule); do not "clean up"
these strings at the connector.

Safety ceiling: `_MAX_OFFSET = 1000` (≤51 pages) even if the tenant ignores
`searchText`. Keep `search.yaml` role anchors tight — the title-gate's
aggressiveness determines how many detail fetches are issued.

**Throttle-resilient.** A big board fires many list + detail requests, so both
HTTP calls carry the retry — but that retry is no longer Workday's own. It is
the default policy of every board endpoint and lives in `http.py` with the
pool: transient statuses (`429`, `500`, `502`, `503`, `504`) are retried with
backoff, honoring a numeric `Retry-After` when present, else exponential
(`RETRY_BACKOFF_S · 2ⁿ`, capped at `MAX_RETRY_SLEEP_S`), for `RETRY_ATTEMPTS`
tries. `BoardSession` then _returns_ the last transient response rather than
raising, so Workday's `_checked` is what turns an exhausted retry into an
`HTTPStatusError` — which is what lets a persistently-throttled board surface
as a per-URL failure (the companies connector isolates it) rather than aborting
sibling URLs. Workday's `_RETRY_*` names now alias the shared constants.

**Detail fetches are concurrent.** `harvest_detailed` fans the _detail_ half of
the N+1 out across `Settings.detail_fetch_concurrency` (default 4) threads, each
running in its own `copy_context()` so the run's pool and the active
`UserContext` survive the hop. The title gate and the final relevance gate stay
where they were, results stay in row order, and the `limit` early-break holds
exactly: chunk size is `min(concurrency, limit - kept)`, so `limit=5` issues 5
detail fetches, not a speculative chunk of 20.

---

## Pooled HTTP (`http.py`)

Every connector calls `board.get` / `board.post` rather than module-level
`httpx.get`, which built a fresh client — and therefore a fresh pool, TCP
connection, and TLS handshake — per request.

- **Connectors talk HTTP through one pooled seam.** `discovery/connectors/http.py`'s
  `BoardSession` owns the connection pool, the single `timeout` (it was a bare
  `timeout=30` in ~15 modules), and the 429/5xx retry that only Workday had.
  `board_session()` installs one per pull run through a `ContextVar`, so worker
  threads inherit it and its connections are released when the run ends; a
  connector called outside a run gets a private session and behaves
  identically. Measured: 1.0 → 12.0 requests per client on one host.
  **Scope is operator-configured endpoints only** — board APIs and ATS API URLs
  rebuilt from a validated `AtsTarget`. A user-supplied URL still goes through
  `security/outbound.py`, and that gateway is deliberately **not** given this
  pool: it pins each request to the IP it validated and carries the hostname in
  an `sni_hostname` extension, but httpx keys its pool on the request origin
  (the IP), so a shared pool could hand a connection negotiated with one
  hostname's SNI to a request for another hostname on the same address.

`get`/`post` keep `httpx.get`'s contract — they **return** the response and do
not raise for status — so a call site that tolerates a 404 or inspects the
status is unchanged. Only transient statuses are retried before that response
comes back.

Tests fake at this seam — `monkeypatch.setattr(<module>.board, "get", ...)` —
not at `httpx`.

---

## Tesla/Google portals (`tesla.py`, `google.py`)

- **Tesla/Google portals are reverse-engineered.** Google's `ds:1`
  `AF_initDataCallback` carries complete list rows and full JDs; a missing or
  malformed jobs callback raises a per-URL parse failure. Tesla's site is
  Akamai-gated: the visible `TeslaPortal` only passes with **real Chrome**
  (`channel="chrome"`), `--disable-blink-features=AutomationControlled` (so
  `navigator.webdriver` is `false`), and a **fresh non-persistent context** (a
  persistent profile keeps a poisoned `_abck` cookie from a prior denial). All
  three are required; bundled Chromium or `webdriver=true` is served "Access
  Denied" and the `state` XHR never fires. `_capture_state` retries past a
  throttled cold denial and raises `TeslaStateUnavailable` (isolated by
  `_failure_reason`, never aborting the pull). Live schema: listing location is
  a code resolved via `state.lookup.locations`; the detail endpoint is
  `cua-api/careers/job/{id}` (no `apps/`) and JD prose lives in
  `jobDescription`/`jobResponsibilities`/`jobRequirements`/`jobCompensationAndBenefits`
  (`description` is empty). A companies connector containing Tesla opts out of
  concurrent fetch and is serialized with other visible-browser connectors by
  the pull runner. Either portal can change without notice, but its failure
  never aborts other company URLs.

## Per-source-unit limits

- **Limits are per source unit.** Every board, careers URL, aggregator, and
  scrape target can set an optional positive `limit` in `connectors.yaml` or
  Source Manager. The global `--limit` is the per-unit fallback; `harvest`
  gates, skips known rows, and caps each unit independently, never the union.

## Adzuna enrichment (`adzuna.py`)

- **Adzuna enrichment needs a real (non-headless) browser.** The API returns
  only a truncated snippet, and `redirect_url` is a bot-gated `/land/ad/`
  click-tracker — bare `httpx` gets `403` and _headless_ Chromium is challenged
  ("suspicious behaviour"); only a non-headless browser follows the redirect to
  the employer/aggregator posting (Dice, Greenhouse, …). So
  `AdzunaConnector.fetch` (when `enrich_details=True`, the default)
  relevance-gates the snippets, then `enrich_adzuna_jobs` calls
  `browser.render_pages` to drive **one shared visible browser context** over
  every survivor's `redirect_url` (distinct ads are safe; re-clicking the
  _same_ ad boomerangs to a search page), captures each post-redirect
  `final_url`, and extracts the JD via `enrich_adzuna_job(job, page)`
  (LinkedIn/Greenhouse branches, else JSON-LD → description selectors →
  whole-page markdown, taking the **first** materially-richer candidate in
  specificity order, with logo `![](…)` images stripped). Any render/extract
  failure leaves the snippet intact and is recorded in `.failures`. Enrichment
  is un-exercised by the offline suite (the browser is faked); a pull is
  slower and pops a window.

## Relevance gates (`text.py`)

| Function               | When used                                                                                                                               |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `title_relevance_gate` | Before JD text is available (Workday list rows, Tesla listing state)                                                                    |
| `relevance_gate`       | Full gate on title + JD; falls back to keyword search when no `role_anchors` are configured                                             |
| `primary_search_term`  | Picks the strongest term to send as `searchText` to Workday / Google; falls back to `role_anchors` if `titles` and `keywords` are empty |
| `primary_location`     | Picks the first configured location for ATS endpoints such as Lever that accept a free-form location filter                             |
