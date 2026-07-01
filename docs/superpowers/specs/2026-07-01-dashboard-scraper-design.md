# Generic Learned-Recipe Dashboard Scraper — Design

**Date:** 2026-07-01
**Status:** Approved design, pre-plan
**Depends on:** the skip-known pull work (`2026-07-01-skip-known-pull.md`) for the
`skip_seen` predicate reused during card enumeration.

## Context

The discovery layer covers job boards through deterministic, reverse-engineered
HTTP/JSON backends (Greenhouse, Lever, Ashby, Workday, SmartRecruiters, …), each
detected by `detect_ats` and dispatched via `companies._BACKENDS`. Some
company-owned career dashboards run on no recognizable ATS and expose no usable
JSON API — they are bespoke, JavaScript-rendered boards. Today `detect_ats` returns
`None` for these and the URL is recorded as "no known ATS detected."

This spec adds an **opt-in** connector that scrapes such dashboards with a real
browser, guided by a **learned, cached selector recipe**. It is the deferred "learn
the structure, then drive Playwright over search + pagination" capability, split out
from the deterministic connector-expansion work so its non-deterministic, browser- and
LLM-driven concerns stay isolated.

The design is a direct generalization of the existing `LinkedInScraper`
(`discovery/scraper/linkedin.py`): the same persistent-context lazy-launch, the same
enumerate-cards → per-card-detail → `FetchResult` shape, the same test seam
(subclasses stub `_search_html`/`_detail_html` so no browser launches offline). The
only difference is that the CSS selectors and pagination pattern are **learned by an
LLM and cached**, instead of hardcoded.

## Goals

1. Pull jobs from an explicitly-configured list of arbitrary company-owned dashboards.
2. Invoke the LLM only to **learn/relearn** a per-host recipe (cached) and as a
   **per-card extraction fallback**; every other step is deterministic replay.
3. Drive the site's **search box + pagination** to narrow and walk results, reusing
   the enumerate → title-gate → skip-known → detail discipline so the crawl stays
   affordable.
4. Stay inside the offline test suite (faked browser, faked LLM), exactly like the
   LinkedIn scraper.

## Non-goals (deferred)

- Driving **structured filter widgets** (location dropdowns, remote toggles). Fast-
  follow; the local `relevance_gate` already enforces correctness, so filter driving
  is a pure efficiency optimization.
- **Vision/screenshot-based** learning (coordinates from images). Recipe learning uses
  pruned HTML → CSS selectors.
- **Multi-company-per-host** recipe keying. These targets are one company per host.
- Automatic fallback from `companies.urls`. Routing is explicit opt-in (see below).

## Core decisions (from grilling)

1. **Extraction = hybrid.** LLM learns a selector+pagination recipe once per host
   (cached); deterministic Playwright replay on every pull; `extract_fields`
   (`url_ingest/llm.py`) runs per-card **only** when the recipe's detail parse yields
   an empty JD.
2. **Recipe lifecycle.** A pydantic `ScrapeRecipe` with `schema_version` + `learned_at`,
   persisted as JSON at `data/scraper_recipes/{host}.json`, keyed by normalized host.
   Learn on cache-miss; **guarded auto-relearn once** when replay yields zero cards
   **and** a sentinel (`has_job_like_content`) says the page really has job content
   (so a legitimately-empty search never triggers a relearn); `--relearn` escape hatch.
   A `schema_version` mismatch is treated as a cache-miss.
3. **Crawl = search bar + pagination.** The recipe learns the search input + submit and
   the pagination control/pattern. Drive the primary search term through the box, walk
   pages up to a `max_pages` ceiling, enumerate cards, then `title_relevance_gate` +
   `skip_seen` prune **before** any detail-page fetch. Structured filters deferred.
4. **Routing = explicit opt-in.** A dedicated `scrape:` config section (its own
   connector), enabled by default off — like the LinkedIn connector. `detect_ats` →
   `None` keeps meaning "candidate for a real backend", not "silently scrape."

## Architecture / file structure

New package `discovery/scraper/` additions (alongside `linkedin.py`):

- **`recipe.py`** — `ScrapeRecipe` (pydantic, pure):
  - `schema_version: int`, `learned_at: datetime`
  - `card_container: str` — selector matching one job card in the results list
  - `title_sel: str | None`, `location_sel: str | None`, `url_sel: str | None` —
    selectors resolved **relative to** a card (url_sel resolves an `href`)
  - `detail_mode: Literal["link", "inline"]` — follow the card url, or the JD is on the
    list page already
  - `jd_container: str` — selector for the JD body on the detail (or inline) page
  - `pagination: Pagination` — `pattern: Literal["numbered","next","infinite","load_more"]`,
    `control_sel: str | None`, `max_pages: int`
  - `search: Search | None` — `input_sel: str`, `submit_sel: str | None`
- **`recipe_store.py`** — `load_recipe(host) -> ScrapeRecipe | None`,
  `save_recipe(host, recipe)`, `recipe_path(host)`; `RECIPES_DIR = "data/scraper_recipes"`;
  a `schema_version` mismatch or JSON error returns `None` (cache-miss).
- **`learn.py`** — `prune_html(html) -> str` (drop script/style/noscript/svg/comments,
  collapse whitespace, truncate to a char/token budget), `build_learn_agent(model_id=None)
  -> Runner` (agno agent with `output_schema=ScrapeRecipe`, mid/premium tier, JSON mode,
  `retry_kwargs`, untrusted-input instructions mirroring `url_ingest/llm.py`),
  `learn_recipe(pruned_html, agent) -> ScrapeRecipe`.
- **`recipe_parse.py`** — pure, deterministic, BeautifulSoup:
  - `parse_cards(html, recipe) -> list[ScrapedCard]` (reuses `scraper/models.ScrapedCard`)
  - `parse_detail(html, recipe) -> str` (JD via `jd_container`, run through
    `html_to_markdown`, cleaned; candidate selection borrowing Adzuna's
    `is_materially_richer` guard against chrome)
  - `has_job_like_content(html) -> bool` — the relearn sentinel (e.g. page text has
    multiple job-ish anchors / a results count / N repeated sibling blocks)
- **`dashboard.py`** — `DashboardScraper` connector (mirrors `LinkedInScraper`):
  lazy persistent non-headless context; stubbable `_search_html(target, search)`,
  `_page_html(next control)`, `_detail_html(card)`; recipe learn/relearn orchestration;
  enumerate → gate → skip → detail; per-card `extract_fields` fallback; returns
  `FetchResult` with per-target failures isolated. `fetch(search, limit=None, skip_seen=None)`.
- **`connectors/config.py`** — `ScrapeTarget{url, enabled, label}`,
  `ScrapeConfig{enabled=False, targets=[]}`; add `scrape: ScrapeConfig` to `ConnectorsConfig`.
- **`connectors/registry.py`** — build `DashboardScraper` in `build_connectors` and
  `build_source_connectors` (source id `scrape:{host}`), gated on `config.scrape.enabled`.
- **`discovery/source_tier.py`** — add `"scrape"` to `_CANONICAL`.
- **`cli.py`** — `resume-agent pull --relearn` forces a fresh learn (ignores cached recipe).

## Data flow

```
DashboardScraper.fetch(search, limit, skip_seen):
  for target in enabled scrape targets:
    host = normalize(target.url)
    recipe = None if relearn else load_recipe(host)
    if recipe is None:
        recipe = learn_recipe(prune_html(_search_html(target, search)), agent); save_recipe(host, recipe)
    html = _search_html(target, search)             # goto url; if recipe.search: fill primary_search_term + submit
    cards = collect_cards(html, recipe)             # parse_cards across pages via recipe.pagination, capped max_pages
    if not cards and has_job_like_content(html) and not relearned:
        recipe = learn_recipe(prune_html(html), agent); save_recipe(host, recipe); relearned = True
        cards = collect_cards(html, recipe)
    cards = title_relevance_gate(cards, search)
    cards = [c for c in cards if not (skip_seen and skip_seen(c))]   # skip-known, pre-detail
    for card in cards:
        detail_html = _detail_html(card)            # follow card.url when detail_mode == "link"
        jd = parse_detail(detail_html, recipe)
        if not jd:
            jd = extract_fields(html_to_text(detail_html), agent).jd_text   # per-card self-heal
        if jd: emit RawJob(source="scrape", url=card.url, company/title/location=card.*, jd_text=jd)
  return gate_and_limit(union) with per-target failures
```

`primary_search_term` / `primary_location` (from `connectors/text.py`) supply the box
input. Enumeration reuses `ScrapedCard` and the LinkedIn card-dedupe pattern.

## Error handling

- **Per-target isolation:** any single target that fails (learn error, browser nav
  error, zero cards after a guarded relearn) records a `failures[url] = reason` and the
  run continues — same contract as `CompaniesConnector`/`LinkedInScraper`.
- **Empty detail parse** → LLM `extract_fields` fallback → still empty → skip that card.
- **`max_pages` ceiling** bounds a misidentified pagination control.
- **Browser launch failure** isolates to the connector run (the whole scraper records a
  failure), mirroring `LinkedInScraper._close_browser`/`render_pages`.
- The guarded relearn runs **at most once per target per pull** (bounded LLM cost).

## Testing (all offline; browser + LLM faked)

- **`recipe_parse`:** fixture HTML + a hand-written `ScrapeRecipe` → expected
  `ScrapedCard`s and JD text; `has_job_like_content` true/false fixtures.
- **`learn`:** `prune_html` unit (script/style/comment removal, truncation); a faked
  agent returning a `ScrapeRecipe`.
- **`recipe_store`:** save→load round-trip; `schema_version` mismatch → `None`; host
  normalization; corrupt JSON → `None`.
- **`dashboard`:** a `DashboardScraper` subclass stubbing `_search_html`/`_page_html`/
  `_detail_html`, a fake learn agent, and an in-memory recipe store — assert: learn on
  cache-miss then cached (learn called once across two pulls); enumerate → title-gate →
  skip_seen prune before detail; guarded relearn fires exactly once on
  empty-cards-with-content and not on empty-without-content; `extract_fields` fallback
  fires only when `parse_detail` returns empty; per-target failure isolation. No browser,
  no real LLM.

## Invariants preserved

- **Fact-lock:** untouched — scraped JD is source text; facts come from the profile.
- **Source priority:** `source="scrape"` is canonical (added to `_CANONICAL`), so
  dedupe/upgrade/skip-known treat it as a direct source.
- **Skip-known:** reused verbatim via the injected `skip_seen` predicate.
- **Offline determinism:** replay + parse are pure; the two LLM touchpoints are faked.

## Operator responsibility (flagged, not designed away)

Scraping arbitrary third-party sites carries ToS/legal considerations. This connector
is **opt-in and disabled by default**, gated per-URL in config, consistent with how the
LinkedIn scraper is gated behind an explicit enable + burner profile. Respecting a
target's terms and robots policy is the operator's responsibility.

## Build phases (for the plan)

1. `recipe.py` model + `recipe_store.py` (pure; JSON round-trip + versioning).
2. `recipe_parse.py` (pure; fixture-tested cards/detail/sentinel).
3. `learn.py` (LLM seam; `prune_html` + faked-agent learn).
4. `DashboardScraper` + config + registry + `source_tier` + CLI `--relearn` (wires the
   above into a connector; stubbed-browser tests).
