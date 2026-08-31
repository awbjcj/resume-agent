# Add Job by URL — Design

**Date:** 2026-06-16
**Status:** Approved (design); pending implementation plan

## Problem

Manual job-adding (`resume-tailor-harness addjob`) requires the user to paste the full
job-description text and hand-type company/title/location. The user wants to
instead paste **just a URL** — from LinkedIn, Greenhouse, or an arbitrary
company careers page — and have the tool fetch the page and self-extract the
fields needed for ingestion.

## Runtime constraint

"Web fetch with an LLM" must be re-interpreted for this app's runtime. Claude
Code's `WebFetch` tool does not exist when the app runs standalone (CLI /
Streamlit). The feature is therefore built from pieces that already have a
sibling pattern in the repo, with **no new dependencies** (`httpx`,
`beautifulsoup4`, `playwright`, `agno` are all already declared):

- an **HTTP client** (`httpx`) for static pages,
- the **existing Playwright persistent-context driver** for JS / login-gated
  pages (reuses the logged-in LinkedIn burner profile),
- an **Agno + Claude extractor agent** mirroring `discovery/extract.py`.

## Key decisions

1. **Fetch strategy: HTTP-first, Playwright fallback.** Static pages
   (Greenhouse, company sites) are fetched with a fast `httpx` GET. `linkedin.com`
   and pages that return a JS shell / empty body are routed through the existing
   logged-in persistent-context browser.
2. **Extraction: known-domain parsers + LLM fallback.** Reuse `scraper/parser.py`
   for LinkedIn and add a deterministic Greenhouse parser; fall back to the LLM
   extractor only for unknown company sites.
3. **Entry point: the `addjob` CLI command.** No dashboard add-UI exists today;
   a dashboard form is out of scope (separate feature).

## Architecture

The feature ends at the existing connector seam: every source already produces a
`RawJob` that flows through `add_job()` for normalize / dedupe / insert. A URL is
just a new way to produce one `RawJob`, so the new code inherits dedupe, source
tagging, and status handling for free.

### Module layout

New package `src/resume_tailor_harness/discovery/url_ingest/`:

- **`fetch.py`** — `fetch_page(url, *, allow_browser=True) -> PageContent`
  where `PageContent(html: str, final_url: str, rendered: bool)`. HTTP-first
  with browser fallback (see Fetch routing).
- **`greenhouse.py`** — deterministic parser for `boards.greenhouse.io`
  (predictable DOM: `.app-title`, company name, `.location`, `#content`).
- **`llm.py`** — `build_url_extract_agent()` and `extract_fields(text, agent)`,
  an Agno + Claude agent mirroring `discovery/extract.py`, emitting an
  `ExtractedJob` Pydantic schema (`company`, `title`, `location`, `jd_text`,
  all optional except a non-empty `jd_text`).
- **`service.py`** — `job_from_url(url, *, agent, allow_browser=True) -> RawJob | None`.
  Orchestrates fetch (via `fetch_page`, which owns the browser fallback) → domain
  routing → returns a `RawJob` (or `None` when no JD text could be extracted).
  `allow_browser` is threaded through to `fetch_page`.

### Shared browser helper

Lift the persistent-context session logic out of `LinkedInScraper` into a small
reusable `fetch_rendered(url) -> str` (sharing the same logged-in profile / user
data dir) so both the scraper and the URL fetcher use one code path. This is a
targeted improvement to code being touched, not a broad refactor. `LinkedInScraper`
is refactored to call the shared helper; its existing tests (which stub
`_search_html` / `_detail_html`) remain green.

### Fetch routing (`fetch.py`)

1. `httpx.get` with a browser-like User-Agent, redirects followed, short timeout.
2. Use the browser fallback when **either**:
   - the host is `linkedin.com`, **or**
   - the HTTP body looks like a JS shell (tiny `<body>`, no recognizable
     job-description container).
3. `allow_browser=False` (CLI `--no-browser`) forces HTTP-only and skips the
   fallback.

### Extraction routing (`service.py`)

- `linkedin.com` → reuse `scraper/parser.py`. Add `parse_detail_meta(html)` to
  pull `title` / `company` / `location` from a LinkedIn **detail** page's top
  card; `parse_job_detail(html)` already returns the JD body.
- `boards.greenhouse.io` → `greenhouse.py`.
- Anything else → clean HTML to readable text (strip `script` / `style` / nav
  chrome) → `llm.py` extractor.
- If the resulting JD text is empty → return `None`.

### CLI wiring (`addjob`)

Extend the existing command in `cli.py`:

- `--url` provided **and no JD source** (`stdin` / `--jd-file`) → fetch + extract,
  echo the extracted `company` / `title` / `location`, then
  `add_job(source="url", ...)`.
- Explicit `--company` / `--title` / `--location` flags **override** extracted
  values (manual correction).
- A JD piped on stdin or via `--jd-file` still wins; extraction only runs when no
  JD text is supplied (current behavior unchanged for existing invocations).
- New `--no-browser` flag forces HTTP-only fetching.

## Error handling

Network error, non-HTML content, or empty extraction → a clear `typer` message
and non-zero exit. Never insert a junk or empty JD — this mirrors the parser's
existing "empty → skip" stance (`parse_job_detail` returns `""` rather than
ingesting page chrome).

## Testing

- **`fetch.py`** — monkeypatch `httpx` and the browser helper; assert routing:
  LinkedIn → browser, JS-shell body → browser, static HTML → HTTP, and
  `allow_browser=False` → never calls the browser.
- **`greenhouse.py`** and **LinkedIn `parse_detail_meta`** — HTML fixtures under
  `tests/fixtures/` (same style as `tests/fixtures/linkedin/`); pure-function
  parser tests.
- **`service.py`** — fake fetch + fake agent; assert the correct `RawJob` per
  domain and `None` on empty JD.
- **CLI** — a fake `job_from_url` (same seam style as `_FakeBrowserScraper`);
  assert flag precedence (manual flags override extracted), the `--no-browser`
  path, and the duplicate-job message.

## Out of scope (YAGNI)

- A dashboard add-by-URL form (no add UI exists today — separate feature).
- An interactive confirm / preview-before-insert step (the CLI echoes extracted
  fields and inserts; flags override).
