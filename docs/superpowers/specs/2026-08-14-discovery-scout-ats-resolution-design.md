# Discovery Scout ATS Resolution Accuracy Design

**Date:** 2026-08-14

**Status:** Approved design

**Scope:** Discovery Scout company-source research, deterministic ATS ownership verification, and manual confirmation

## Problem

The Discovery Scout currently asks the research model to find a company careers URL and then calls `check_source(url)`. The tool and the post-processing pass prove that the URL is reachable, maps to a supported connector, and can return jobs. They do not prove that the board belongs to the company named in the proposal.

That distinction creates false verification. A reachable Workday, Lever, or other ATS board can be marked `validated` even when it is stale, unrelated, or belongs to a similarly named company. Re-running the same URL through `preview_source()` does not close the gap because both checks validate the board, not company ownership. Repeated ATS guessing also consumes the web-search allowance and makes a search rate limit more likely.

Current examples that must become regression cases are:

- Intuitive must resolve to its SmartRecruiters board, not Workday.
- Tempus must resolve to its Workday board, not Lever.

The desired policy is accuracy-first but not silent: the Scout should do its bounded best to find the correct board. If it finds a plausible URL but cannot prove company ownership, it should show the candidate as unverified, prevent ordinary addition, and allow only an explicit warned manual confirmation.

## Goals

1. Resolve a selected company to the correct durable board root for every ATS family the application supports.
2. Prefer first-party provenance over search-result ranking or model confidence.
3. Make supported-ATS search coverage systematic and derived from code rather than a stale prompt list.
4. Reduce repeated web searches by crawling and inspecting candidate pages deterministically.
5. Ensure search failures and rate limits can only reduce confidence, never validate a guess.
6. Preserve useful best-effort candidates as unverified with a clear reason and evidence summary.
7. Require an explicit, auditable confirmation before adding an unverified candidate.
8. Keep all configuration writes behind the existing deterministic source service and user approval boundary.

## Non-goals

- Guaranteeing that every company has a supported ATS or publicly discoverable board.
- Building a general-purpose search engine or unrestricted web crawler.
- Automatically adding any source found by the agent.
- Treating search-result consensus, token similarity, or model confidence as proof of ownership.
- Making live internet checks part of the deterministic CI suite.
- Refactoring unrelated connectors, pull behavior, or search-term recommendations.

## Core decision

Use a first-party provenance resolver. The agent searches for the company and likely official careers pages; deterministic code follows those pages to supported ATS candidates, canonicalizes and probes the candidates, and independently decides whether the evidence binds the board to the company.

The model may choose companies, formulate searches, and supply candidate pages. It may not assign resolution status, repair a candidate into a different URL, or claim that a board belongs to a company. Python owns those decisions.

## Architecture

### Agent tool boundary

Replace source-side use of `check_source(url)` with an identity-aware read-only tool:

```text
resolve_company_source(company, candidate_url)
```

The old bounded source probe remains useful as a low-level operation, but it is not sufficient to validate a company proposal. The new tool returns JSON and never writes configuration.

`resolve_company_source` delegates to a `CompanySourceResolver` with focused collaborators:

1. **SupportedBoardCatalog** describes every supported board family, its search hosts, URL patterns, aliases, canonicalization rules, and available identity signals. The Scout prompt and targeted ATS search groups are rendered from this catalog. Connector additions must update the catalog through the same registration seam, and a synchronization test prevents detector, registry, and search coverage from drifting.
2. **FirstPartyCrawler** inspects a bounded company or careers page and follows relevant careers/jobs links, HTTP redirects, canonical links, embedded URLs, scripts, and ATS markers. It does not follow arbitrary site navigation.
3. **AtsCandidateInspector** identifies candidate ATS URLs, reduces posting URLs to durable board roots, and uses the existing connector preview path to check reachability, ATS kind, token or Workday identity, and role availability.
4. **CompanyOwnershipVerifier** evaluates the provenance chain and provider metadata against the proposed company and any discovered brand aliases. It alone assigns the resolution status.

Each unit has a narrow interface and can be fixture-tested independently. Network access continues through the existing outbound security gateway.

For this feature, a first-party page is an HTTPS page on the registrable corporate domain identified by the official-company search result, or one of that domain's subdomains. Leaving that domain is permitted only through a recorded redirect or link to a supported careers/ATS destination; the crawler does not promote an arbitrary third-party page to first-party merely because it repeats the company name.

### Resolution result

The resolver returns a structured value similar to:

```text
CompanySourceResolution
  company
  requested_url
  canonical_board_url
  ats
  token
  role_count
  status: verified | unverified | conflict | failed
  reason_code
  evidence[]
  searched_families[]
  unsearched_families[]
```

Evidence entries record their type, source URL, destination URL when applicable, and a concise deterministic summary. Raw page bodies and search snippets are not persisted in the Scout session.

The existing proposal `check` field remains the compatibility projection used by the current UI and service:

| Resolution status | Proposal check |
| --- | --- |
| `verified` | `validated` |
| `unverified` | `unverified` |
| `conflict` | `conflict` |
| `failed` | `failed` |

`duplicate` and `avoid` remain proposal-level states outside source resolution.

### Deterministic post-processing

Agent notes may contain a proposed company and candidate URL, but not a trusted status. Scout post-processing resolves every fresh positive source again, using the per-session resolver cache where the exact normalized company and URL were already checked during the tool loop. The final proposal is populated only from `CompanySourceResolution`.

This preserves the existing generate, verify, and explicitly approve architecture while upgrading verification from “live supported board” to “live supported board belonging to this company.”

## Supported-board search coverage

The Scout instructions receive a compact search catalog rendered from `SupportedBoardCatalog`. It must cover all generic ATS families currently supported:

- Greenhouse
- Lever
- Ashby
- Workday
- SmartRecruiters
- Workable
- Recruitee
- Personio
- Breezy
- JazzHR
- BambooHR

Supported bespoke company portals such as Google and Tesla remain discoverable through their deterministic singleton detection, but they are not represented as generic ATS host families.

The prompt names canonical hosts and gives query shapes without hard-coding a separate authoritative list. For example:

```text
"Intuitive" official careers jobs
"Intuitive" jobs (site:jobs.smartrecruiters.com OR site:careers.smartrecruiters.com)
```

Company aliases and the known corporate domain are included when available to disambiguate common names. Search results identify candidates; they never establish ownership on their own.

## Search and resolution flow

Resolution runs in the following order for a group of selected companies:

1. The research agent shortlists companies relevant to the user's goal.
2. It searches for their official company or careers pages, batching companies into a combined query when useful.
3. For each company, it calls `resolve_company_source(company, candidate_url)` on the most credible first-party candidate.
4. The resolver follows first-party careers links, redirects, embeds, and markers and probes every bounded ATS candidate it discovers.
5. If no candidate verifies, the agent uses its remaining search allowance on targeted queries covering the supported ATS host groups. Providers are grouped into a small number of queries rather than tried one by one.
6. Newly discovered candidates go through the same resolver. A direct ATS result can still verify when strong provider-owned organization metadata proves the company identity; otherwise it remains unverified.
7. Resolution stops for a company as soon as strong ownership proof and a live canonical board are established.
8. Post-processing deterministically reproduces or reuses the exact resolution before rendering the proposal.

The agent must never construct a likely ATS slug and present it as a finding. Guessed variants may be inspected as candidates only when the bounded search/crawl flow surfaces evidence for them.

## Ownership evidence and status rules

### Strong ownership evidence

Any of the following may establish ownership when the company identity is unambiguous:

- A link or redirect from the company's first-party site to the exact canonical ATS board.
- A first-party wrapper careers site with a preserved redirect, embed, script, or API provenance chain to the board.
- Provider-owned organization metadata that identifies the company and, where available, its official domain.

Multiple compatible strong signals may be combined. The verifier normalizes ordinary brand and legal-name variations but does not collapse unrelated companies that merely share a word.

### Candidate-only evidence

The following may rank a candidate for inspection but cannot independently produce `verified`:

- A search result or search snippet.
- A similar ATS token or subdomain.
- The company name appearing only inside a job description.
- A non-first-party directory, aggregator, social post, or cached job posting.
- The research model's confidence or prose assertion.

### Status definitions

- **verified:** a reachable supported board has strong ownership evidence for the proposed company.
- **unverified:** a plausible candidate exists, but ownership evidence is incomplete, search coverage was interrupted, or only candidate-level evidence is available.
- **conflict:** strong evidence identifies the board as belonging to a different company.
- **failed:** no usable candidate was found, the URL was invalid or unreachable, or resolution could not inspect it safely.

A live role count of zero does not by itself invalidate a verified durable board. Conversely, a populated board does not prove ownership.

## Search budget and rate-limit behavior

Search is provider-aware and bounded at the Scout orchestration layer. The default cross-provider ceiling is five web-search calls per Scout turn, matching the most restrictive native search plan currently supported. The effective allowance is rendered into the prompt and enforced through the provider's native maximum where available, the fallback search wrapper, and the existing overall tool-call limit. A future provider-specific increase must preserve the same batching, circuit-breaker, and coverage-reporting rules.

Searches are budgeted across the turn:

1. discover and shortlist companies;
2. run a combined official-careers query;
3. inspect resulting pages through direct HTTP without spending search calls;
4. spend remaining calls only on unresolved companies and grouped ATS-host searches.

Resolver results are cached for the Scout session by normalized company and requested URL. Repeated refinement messages and post-processing reuse the exact result when it remains applicable. An edited URL is a new cache key and receives fresh resolution.

On a search-specific rate limit, the search circuit opens for the remainder of the turn. The Scout preserves companies already resolved and does not repeatedly retry the same query or ATS family. Unresolved candidates remain unverified. A provider-level transient retry must reuse completed resolver results and must not turn the retry into an expanded search budget.

Canonical reason codes include:

- `SEARCH_RATE_LIMITED`
- `SEARCH_BUDGET_EXHAUSTED`
- `OFFICIAL_SITE_UNREACHABLE`
- `ATS_NOT_FOUND`
- `OWNERSHIP_NOT_PROVEN`
- `ATS_CONFLICT`
- `RESOLUTION_TIMEOUT`
- `UNSAFE_URL`

Failures are isolated per company. The initial defaults are at most five first-party pages, five ATS candidates, five redirects per request, and 1 MiB of response text per page; a 15-second request timeout and 45-second overall resolution deadline per company; and four concurrent company resolutions. These are named policy constants, not prompt text, so they can be tuned with regression evidence without changing trust semantics.

## Proposal, API, and approval behavior

### Proposal payload

Source proposals expose the canonical candidate URL, detected ATS details, resolution status and reason, a concise evidence summary, and searched/unsearched ATS families. Evidence URLs remain untrusted HTTP(S) data and use the existing safe rendering and egress rules.

### Normal approval

The existing proposal approval route continues to add search terms and verified sources without a required request body. It no longer accepts an unverified source through the ordinary path.

The current meaning of `unverified` as “automatically add this as a scrape target when a browser is available” changes for Scout proposals: unverified means company ownership has not been proven, so explicit confirmation is required. Source Manager's separate explicit scrape workflow remains available.

### Manual confirmation

The approval request gains an optional manual-confirmation payload. For an unverified source, the UI shows the exact company, canonical URL, detected ATS, evidence summary, and reason verification was incomplete. The user must affirm that they opened the candidate and believe it belongs to the company.

The server accepts manual confirmation only when all of these remain true:

- the proposal is pending and unverified;
- the company and URL exactly match the proposal shown in that Scout session;
- the URL has not changed since resolution;
- the proposal is not `conflict`, `failed`, `avoid`, or `duplicate`.

A manually confirmed known ATS board is added through the existing automatic provider path. A generic careers page with no detected ATS can be added as a scrape target only when browser scraping is available; otherwise confirmation remains blocked with a precise reason.

Before adding, the session records the session id, proposal id, company, exact URL, detected ATS, resolution reason, confirmation timestamp, and that the user explicitly overrode automated ownership verification. The configuration mutation still goes through `add_source()`.

### Correcting a candidate

An unverified proposal offers “Try another URL.” A read-only resolution action accepts a replacement HTTP(S) URL for the same company, invalidates prior resolution and confirmation state, runs the deterministic resolver, and updates the pending proposal. If the replacement verifies, the normal Add action becomes available.

### UI states

- **Verified:** show ATS, role count when available, evidence summary, and `Add source`.
- **Unverified:** show the reason, searched coverage, `Open board`, `Try another URL`, and `Confirm & add anyway`; ordinary Add is disabled.
- **Conflict:** show the identified mismatch and require another URL; no override is offered.
- **Failed:** show the failure reason and allow another search or replacement URL.

The confirmation dialog is keyboard accessible, moves focus predictably, names the company and destination URL, and makes the override warning available to assistive technology.

## Security and trust boundaries

- User text, model output, search results, page content, ATS metadata, and evidence URLs remain untrusted data.
- Agent tools stay read-only. They cannot add sources, update proposals directly, or write configuration.
- All outbound requests use the existing SSRF and DNS-rebinding protections.
- Crawling is restricted to HTTP(S), bounded redirects, first-party careers navigation, and discovered supported ATS candidates.
- Raw remote instructions never enter the system prompt as instructions.
- Manual confirmation is scoped to an existing pending proposal and exact URL; it is not a general bypass that accepts arbitrary source mutations.

## Testing strategy

### Offline golden corpus

Create captured search, HTML, redirect, embed, and ATS-response fixtures for:

- Intuitive resolving to SmartRecruiters;
- Tempus resolving to Workday;
- at least one company for every supported ATS family;
- first-party wrapper sites and multi-hop redirects;
- posting URLs that must canonicalize to board roots;
- stale boards and old indexed results;
- similarly named companies and unrelated populated boards;
- provider metadata conflicts;
- search-only candidates;
- rate limits, exhausted budgets, timeouts, unsafe redirects, and partial coverage.

### Unit tests

- The supported-board catalog and prompt renderer cover every registered supported ATS family.
- Detector, canonicalizer, and search-host metadata cannot drift silently.
- First-party crawling preserves the provenance chain while respecting all bounds.
- Ownership evidence maps to the correct status and never treats candidate-only evidence as proof.
- Canonicalization removes posting paths, locale segments where applicable, filters, and tracking parameters.
- Resolver cache keys include normalized company identity and requested URL.
- A rate limit opens the search circuit and does not erase completed resolutions.

### Service and API tests

- Model-provided status or ATS claims are ignored and recomputed.
- Post-processing reuses only an exact cached resolution.
- Ordinary approval accepts verified sources and rejects unverified sources.
- Manual confirmation accepts only the exact pending unverified company/URL pair.
- URL edits invalidate previous confirmation.
- Conflict, failed, avoid, and duplicate states cannot use the override.
- Known ATS and generic scrape overrides route through the correct existing source-service path.
- The confirmation audit record survives session reload.
- One company's failure does not abort other proposals.

### Frontend tests

- Each status renders its evidence and reason accurately.
- Unverified proposals have no ordinary Add action.
- Opening, replacing, rechecking, and manually confirming a URL follow the expected state transitions.
- The confirmation dialog shows the exact company and URL and is accessible by keyboard and screen reader.
- Stale sessions, changed URLs, and rejected confirmations surface actionable errors.
- Batch Add includes verified sources and eligible terms only; it never silently overrides an unverified source.

### Live evaluation

Provide an opt-in live evaluation command that checks the golden-company list against current public sites and reports expected versus resolved ATS and canonical URL. It does not mutate configuration and is not part of CI. Golden expectations carry an evidence timestamp so intentional ATS migrations can be reviewed rather than mistaken for code regressions.

## Acceptance criteria

1. Intuitive resolves to its canonical SmartRecruiters board in the golden corpus.
2. Tempus resolves to its canonical Workday board in the golden corpus.
3. Every supported ATS family is represented in the generated search catalog and resolver tests.
4. No unrelated live board receives `verified` in the golden corpus.
5. Search-only evidence and interrupted coverage produce `unverified`, never `verified`.
6. Search rate limits preserve completed results and do not trigger repeated guessing.
7. Ordinary addition is impossible for an unverified proposal.
8. Explicit confirmation adds only the exact unverified proposal shown and records the override.
9. Conflicting ownership evidence cannot be overridden.
10. Existing verified-source, search-term, and Source Manager approval flows remain functional.

The release target is zero false verified boards in the fixture-backed golden corpus. A false negative may be shown as unverified; a false positive is a correctness failure.
