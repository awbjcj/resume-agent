# Resume Agent — LinkedIn Scraper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add LinkedIn as a real job source: a Playwright driver (persistent logged-in **burner** profile) navigates search + detail pages; **pure HTML-parsing functions** turn that HTML into structured cards and JD text; an orchestrator dedupes and inserts them as `jobs(status=raw)`, ready for the existing discovery funnel. A `scrape` CLI command runs it.

**Architecture — the honest part:** LinkedIn's live DOM cannot be parsed "blind" and changes over time, so this component is **fixture-driven and calibrated**. The parser is plain functions over HTML strings, tested against saved fixtures in `tests/fixtures/linkedin/`. The plan ships realistic _starting_ fixtures + selectors (LinkedIn's guest-job markup, which is comparatively stable) so the tests pass immediately; a dedicated **calibration task** has you save real HTML from your burner session and adjust selectors until the tests pass on _your_ fixtures. The Playwright driver sits behind a `JobSource` protocol and is **not** run in CI (manual verification only); the orchestrator is fully unit-tested with a fake source.

**Tech Stack:** Python 3.13, uv, **playwright** + **beautifulsoup4** (new deps), SQLModel, Typer, pytest. (Reuses `discovery.ingest.add_job` for normalize/dedupe/insert.)

**Depends on:** Discovery (`discovery.ingest.add_job`, `discovery.search_config.SearchConfig/load_search_config`, the `_engine` CLI helper), Foundation (`tracking.tables.JobStatus`, `db`). All merged to `main`.

> **Commit convention:** every commit ends with a second `-m`:
> `-m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"`

---

## Reference & scoped decisions

Design spec §5.2 + Decisions #3/#4 + Risk #1. Decisions for this plan:

- **Parser is pure + fixture-tested.** No network in CI. Saved HTML is the calibration artifact and the regression guard.
- **Driver behind an interface.** `JobSource` protocol with `search(config)` + `fetch_jd(card)`. `LinkedInScraper` (Playwright) implements it; the orchestrator depends only on the protocol, so it tests with a fake.
- **Burner account, persistent context.** `launch_persistent_context(user_data_dir, headless=False)` reuses one saved login; the first run logs in by hand once. Human-like pacing + a result cap. Credentials/data-dir from settings.
- **Manual-assist fallback already exists** (`addjob`); a broken scraper never blocks the user, so the driver is allowed to be the brittle, manually-maintained part.
- **Starting selectors** target LinkedIn's guest-job markup (`base-card`, `base-search-card__title`, `show-more-less-html__markup`) — stable enough to ship as a working baseline; calibration adapts them to whatever your session actually returns.

## File Structure (created/modified)

```
pyproject.toml                                  # MODIFY: add playwright + beautifulsoup4
src/resume_agent/discovery/scraper/
  __init__.py                                   # CREATE
  models.py                                     # CREATE: ScrapedCard dataclass
  parser.py                                     # CREATE: parse_search_cards() + parse_job_detail()
  ingest.py                                     # CREATE: JobSource protocol + ingest_scraped()
  linkedin.py                                   # CREATE: LinkedInScraper (Playwright; not CI-tested)
.gitignore                                      # MODIFY: ignore persistent browser profile + live calibration captures
src/resume_agent/cli.py                         # MODIFY: add `scrape` command
tests/fixtures/linkedin/
  search.html                                   # CREATE: representative search-results HTML
  job.html                                      # CREATE: representative job-detail HTML
tests/
  test_scraper_parser.py
  test_scraper_ingest.py
  test_cli_scrape.py
```

---

## Task 1: Dependencies + ScrapedCard model

**Files:**

- Modify: `pyproject.toml`, `.gitignore`
- Create: `src/resume_agent/discovery/scraper/__init__.py`, `src/resume_agent/discovery/scraper/models.py`
- Test: `tests/test_scraper_parser.py` (model portion only this task)

- [ ] **Step 1: Add dependencies**

Run:

```bash
uv add playwright beautifulsoup4
```

Expected: `pyproject.toml` gains both; `uv.lock` updates; install succeeds. (Browser binaries are installed later in the calibration task, not now.)

- [ ] **Step 2: Ignore local browser sessions and live captures**

Add to `.gitignore`:

```gitignore
.linkedin_profile/
tests/fixtures/linkedin/*_live.html
```

- [ ] **Step 3: Write the failing test**

Create `tests/test_scraper_parser.py`:

```python
from resume_agent.discovery.scraper.models import ScrapedCard


def test_scraped_card_fields():
    card = ScrapedCard(
        job_id="3700000001",
        title="Senior Backend Engineer",
        company="Acme Corp",
        location="Remote, US",
        url="https://www.linkedin.com/jobs/view/3700000001/",
    )
    assert card.job_id == "3700000001"
    assert card.company == "Acme Corp"
```

- [ ] **Step 4: Run to verify it fails**

Run:

```bash
uv run pytest tests/test_scraper_parser.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.discovery.scraper'`.

- [ ] **Step 5: Implement**

Create `src/resume_agent/discovery/scraper/__init__.py`:

```python
"""LinkedIn scraper: Playwright driver + pure HTML parsers (fixture-tested)."""
```

Create `src/resume_agent/discovery/scraper/models.py`:

```python
from dataclasses import dataclass


@dataclass
class ScrapedCard:
    """A single search-result card; `url` + JD text drive ingestion."""

    job_id: str | None
    title: str | None
    company: str | None
    location: str | None
    url: str | None
```

- [ ] **Step 6: Run to verify it passes**

Run:

```bash
uv run pytest tests/test_scraper_parser.py -v
```

Expected: PASS (1 test).

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock .gitignore src/resume_agent/discovery/scraper/__init__.py src/resume_agent/discovery/scraper/models.py tests/test_scraper_parser.py
git commit -m "feat(scraper): deps + ScrapedCard model" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: HTML parsers (fixture-driven)

**Files:**

- Create: `tests/fixtures/linkedin/search.html`, `tests/fixtures/linkedin/job.html`, `src/resume_agent/discovery/scraper/parser.py`
- Test: `tests/test_scraper_parser.py` (append)

- [ ] **Step 1: Create the fixtures**

Create `tests/fixtures/linkedin/search.html`:

```html
<ul class="jobs-search__results-list">
  <li>
    <div
      class="base-card relative"
      data-entity-urn="urn:li:jobPosting:3700000001"
    >
      <a
        class="base-card__full-link"
        href="https://www.linkedin.com/jobs/view/3700000001/?trk=public_jobs"
      >
        <span class="sr-only">Senior Backend Engineer</span>
      </a>
      <h3 class="base-search-card__title">Senior Backend Engineer</h3>
      <h4 class="base-search-card__subtitle">
        <a class="hidden-nested-link">Acme Corp</a>
      </h4>
      <span class="job-search-card__location">Remote, United States</span>
    </div>
  </li>
  <li>
    <div
      class="base-card relative"
      data-entity-urn="urn:li:jobPosting:3700000002"
    >
      <a
        class="base-card__full-link"
        href="https://www.linkedin.com/jobs/view/3700000002/"
      >
        <span class="sr-only">Platform Engineer</span>
      </a>
      <h3 class="base-search-card__title">Platform Engineer</h3>
      <h4 class="base-search-card__subtitle">
        <a class="hidden-nested-link">Beta Industries</a>
      </h4>
      <span class="job-search-card__location">London, UK</span>
    </div>
  </li>
</ul>
```

Create `tests/fixtures/linkedin/job.html`:

```html
<section class="core-section-container">
  <div class="show-more-less-html__markup">
    <p>We are hiring a backend engineer to scale our platform.</p>
    <strong>Responsibilities</strong>
    <ul>
      <li>Design and operate distributed services.</li>
      <li>Improve reliability and latency.</li>
    </ul>
    <strong>Requirements</strong>
    <ul>
      <li>5+ years of Python.</li>
      <li>Experience with Kubernetes.</li>
    </ul>
  </div>
</section>
```

- [ ] **Step 2: Write the failing test**

Append to `tests/test_scraper_parser.py`:

```python
from pathlib import Path

from resume_agent.discovery.scraper.parser import parse_job_detail, parse_search_cards

FIXTURES = Path(__file__).parent / "fixtures" / "linkedin"


def test_parse_search_cards_extracts_each_posting():
    html = (FIXTURES / "search.html").read_text(encoding="utf-8")
    cards = parse_search_cards(html)
    assert len(cards) == 2

    first = cards[0]
    assert first.job_id == "3700000001"
    assert first.title == "Senior Backend Engineer"
    assert first.company == "Acme Corp"
    assert first.location == "Remote, United States"
    assert first.url == "https://www.linkedin.com/jobs/view/3700000001/"  # query stripped


def test_parse_job_detail_returns_clean_text():
    html = (FIXTURES / "job.html").read_text(encoding="utf-8")
    text = parse_job_detail(html)
    assert "backend engineer" in text.lower()
    assert "5+ years of Python." in text
    assert "Kubernetes" in text
    assert "<li>" not in text  # tags stripped
```

- [ ] **Step 3: Run to verify it fails**

Run:

```bash
uv run pytest tests/test_scraper_parser.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.discovery.scraper.parser'`.

- [ ] **Step 4: Implement**

Create `src/resume_agent/discovery/scraper/parser.py`:

```python
from bs4 import BeautifulSoup

from resume_agent.discovery.scraper.models import ScrapedCard


def _text(node) -> str | None:
    if node is None:
        return None
    value = node.get_text(strip=True)
    return value or None


def _strip_query(href: str | None) -> str | None:
    if not href:
        return None
    return href.split("?", 1)[0]


def parse_search_cards(html: str) -> list[ScrapedCard]:
    """Parse a LinkedIn job-search results page into structured cards."""
    soup = BeautifulSoup(html, "html.parser")
    cards: list[ScrapedCard] = []
    for card in soup.select("div.base-card"):
        urn = card.get("data-entity-urn", "")
        job_id = urn.split(":")[-1] if urn else None
        link = card.select_one("a.base-card__full-link")
        cards.append(
            ScrapedCard(
                job_id=job_id,
                title=_text(card.select_one("h3.base-search-card__title")),
                company=_text(card.select_one("h4.base-search-card__subtitle")),
                location=_text(card.select_one("span.job-search-card__location")),
                url=_strip_query(link.get("href") if link else None),
            )
        )
    return cards


def parse_job_detail(html: str) -> str:
    """Extract the job-description text from a LinkedIn job-detail page."""
    soup = BeautifulSoup(html, "html.parser")
    markup = soup.select_one("div.show-more-less-html__markup")
    target = markup or soup
    return target.get_text(separator="\n", strip=True)
```

- [ ] **Step 5: Run to verify it passes**

Run:

```bash
uv run pytest tests/test_scraper_parser.py -v
```

Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/linkedin/search.html tests/fixtures/linkedin/job.html src/resume_agent/discovery/scraper/parser.py tests/test_scraper_parser.py
git commit -m "feat(scraper): fixture-driven LinkedIn HTML parsers" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Ingest orchestrator (JobSource protocol)

**Files:**

- Create: `src/resume_agent/discovery/scraper/ingest.py`
- Test: `tests/test_scraper_ingest.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_scraper_ingest.py`:

```python
from sqlmodel import Session, SQLModel, create_engine

from resume_agent.discovery.scraper.ingest import ingest_scraped
from resume_agent.discovery.scraper.models import ScrapedCard
from resume_agent.discovery.search_config import SearchConfig
from resume_agent.tracking.repository import jobs_by_status
from resume_agent.tracking.tables import JobStatus


class _FakeSource:
    """A JobSource that returns two cards and canned JD text."""

    def __init__(self):
        self.fetched = []

    def search(self, config):
        return [
            ScrapedCard("1", "Backend Engineer", "Acme", "Remote", "https://li/jobs/view/1/"),
            ScrapedCard("2", "Platform Engineer", "Beta", "London", "https://li/jobs/view/2/"),
        ]

    def fetch_jd(self, card):
        self.fetched.append(card.job_id)
        return f"JD for {card.title}"


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_ingest_scraped_inserts_raw_jobs():
    source = _FakeSource()
    with _session() as s:
        added = ingest_scraped(s, source, SearchConfig())
        assert added == 2
        assert source.fetched == ["1", "2"]
        raw = jobs_by_status(s, JobStatus.raw.value)
        assert {j.title for j in raw} == {"Backend Engineer", "Platform Engineer"}
        assert all(j.source == "linkedin" for j in raw)


def test_ingest_scraped_dedupes_on_second_run():
    source = _FakeSource()
    with _session() as s:
        assert ingest_scraped(s, source, SearchConfig()) == 2
        # Same URLs again → all duplicates → nothing added.
        assert ingest_scraped(s, source, SearchConfig()) == 0


def test_ingest_scraped_respects_limit():
    source = _FakeSource()
    with _session() as s:
        added = ingest_scraped(s, source, SearchConfig(), limit=1)
        assert added == 1
```

- [ ] **Step 2: Run to verify it fails**

Run:

```bash
uv run pytest tests/test_scraper_ingest.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.discovery.scraper.ingest'`.

- [ ] **Step 3: Implement**

Create `src/resume_agent/discovery/scraper/ingest.py`:

```python
from typing import Protocol

from sqlmodel import Session

from resume_agent.discovery.ingest import add_job
from resume_agent.discovery.scraper.models import ScrapedCard
from resume_agent.discovery.search_config import SearchConfig


class JobSource(Protocol):
    def search(self, config: SearchConfig) -> list[ScrapedCard]: ...
    def fetch_jd(self, card: ScrapedCard) -> str: ...


def ingest_scraped(
    session: Session,
    source: JobSource,
    config: SearchConfig,
    limit: int | None = None,
) -> int:
    """Pull cards from a source, fetch each JD, and insert raw jobs (deduped). Returns count added."""
    added = 0
    for index, card in enumerate(source.search(config)):
        if limit is not None and index >= limit:
            break
        jd_text = source.fetch_jd(card)
        job = add_job(
            session,
            source="linkedin",
            jd_text=jd_text,
            url=card.url,
            company=card.company,
            title=card.title,
            location=card.location,
        )
        if job is not None:
            added += 1
    return added
```

- [ ] **Step 4: Run to verify it passes**

Run:

```bash
uv run pytest tests/test_scraper_ingest.py -v
```

Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/scraper/ingest.py tests/test_scraper_ingest.py
git commit -m "feat(scraper): JobSource protocol + ingest_scraped orchestrator" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Playwright driver (not CI-tested)

**Files:**

- Create: `src/resume_agent/discovery/scraper/linkedin.py`

> This task has **no unit test** — it drives a real browser against a live, changing site. Its parsing logic is already covered by Task 2's fixture tests; this file is the thin, manually-maintained I/O shell. Correctness is checked in Task 6 (calibration).

- [ ] **Step 1: Implement the driver**

Create `src/resume_agent/discovery/scraper/linkedin.py`:

```python
import time
import urllib.parse

from playwright.sync_api import sync_playwright

from resume_agent.config import get_settings
from resume_agent.discovery.scraper.models import ScrapedCard
from resume_agent.discovery.scraper.parser import parse_job_detail, parse_search_cards
from resume_agent.discovery.search_config import SearchConfig

_SEARCH_URL = "https://www.linkedin.com/jobs/search/"


def _search_url(config: SearchConfig) -> str:
    params = {}
    if config.keywords or config.titles:
        params["keywords"] = " ".join(config.titles or config.keywords)
    if config.locations:
        params["location"] = config.locations[0]
    return _SEARCH_URL + "?" + urllib.parse.urlencode(params)


class LinkedInScraper:
    """Playwright driver over a persistent, logged-in burner profile.

    First run: a browser window opens; log in by hand once. The session persists
    in ``user_data_dir`` for subsequent runs. Pacing is deliberate and capped.
    """

    def __init__(self, user_data_dir: str = ".linkedin_profile", headless: bool = False, pace_seconds: float = 2.0):
        self.user_data_dir = user_data_dir
        self.headless = headless
        self.pace_seconds = pace_seconds

    def search(self, config: SearchConfig) -> list[ScrapedCard]:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(self.user_data_dir, headless=self.headless)
            page = context.new_page()
            page.goto(_search_url(config), wait_until="domcontentloaded")
            time.sleep(self.pace_seconds)
            page.mouse.wheel(0, 4000)
            time.sleep(self.pace_seconds)
            cards = parse_search_cards(page.content())
            context.close()
            return cards

    def fetch_jd(self, card: ScrapedCard) -> str:
        if not card.url:
            return ""
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(self.user_data_dir, headless=self.headless)
            page = context.new_page()
            page.goto(card.url, wait_until="domcontentloaded")
            time.sleep(self.pace_seconds)
            text = parse_job_detail(page.content())
            context.close()
            return text


def build_linkedin_scraper() -> LinkedInScraper:
    settings = get_settings()
    return LinkedInScraper(user_data_dir=getattr(settings, "linkedin_user_data_dir", ".linkedin_profile"))
```

- [ ] **Step 2: Verify it imports (no browser launch)**

Run:

```bash
uv run python -c "from resume_agent.discovery.scraper.linkedin import LinkedInScraper, build_linkedin_scraper; print('import ok')"
```

Expected: prints `import ok` (importing must not launch a browser).

- [ ] **Step 3: Commit**

```bash
git add src/resume_agent/discovery/scraper/linkedin.py
git commit -m "feat(scraper): Playwright LinkedIn driver (persistent burner profile)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: CLI — `scrape`

**Files:**

- Modify: `src/resume_agent/cli.py`
- Test: `tests/test_cli_scrape.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_scrape.py`:

```python
from typer.testing import CliRunner

from resume_agent import cli

runner = CliRunner()


def test_scrape_command_runs_ingest(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"

    monkeypatch.setattr(cli, "load_search_config", lambda path: object())
    monkeypatch.setattr(cli, "build_linkedin_scraper", lambda: object())
    monkeypatch.setattr(cli, "ingest_scraped", lambda session, scraper, config, limit=None: 5)

    result = runner.invoke(cli.app, ["scrape", "--db-url", db_url])
    assert result.exit_code == 0, result.output
    assert "5" in result.output
```

- [ ] **Step 2: Run to verify it fails**

Run:

```bash
uv run pytest tests/test_cli_scrape.py -v
```

Expected: FAIL — `AttributeError: module 'resume_agent.cli' has no attribute 'build_linkedin_scraper'`.

- [ ] **Step 3: Implement**

Add imports near the other imports in `src/resume_agent/cli.py`:

```python
from resume_agent.discovery.scraper.ingest import ingest_scraped
from resume_agent.discovery.scraper.linkedin import build_linkedin_scraper
```

(`load_search_config` is already imported from the Discovery task — do not duplicate.)

Add the command AFTER the `dashboard` command and BEFORE `if __name__ == "__main__":`:

```python
@app.command("scrape")
def scrape_cmd(
    search: str = typer.Option(DEFAULT_SEARCH, help="Path to search.yaml."),
    limit: int = typer.Option(None, help="Cap the number of jobs ingested this run."),
    db_url: str = typer.Option(None, help="Override the database URL."),
) -> None:
    """Scrape LinkedIn for jobs matching search.yaml and insert them as raw jobs."""
    config = load_search_config(search)
    scraper = build_linkedin_scraper()
    engine = _engine(db_url)
    with get_session(engine) as session:
        added = ingest_scraped(session, scraper, config, limit=limit)
    typer.echo(f"Scrape complete. Added {added} new job(s).")
```

- [ ] **Step 4: Run to verify it passes**

Run:

```bash
uv run pytest tests/test_cli_scrape.py -v
```

Expected: PASS (1 test). (The scraper + ingest are patched, so no browser launches.)

- [ ] **Step 5: Verify wiring + full suite**

Run:

```bash
uv run resume-agent scrape --help
uv run pytest -q
```

Expected: help text (exit 0); all tests pass (Tracking total + scraper additions).

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/cli.py tests/test_cli_scrape.py
git commit -m "feat(scraper): scrape CLI command" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Calibration against live HTML (manual — do this on your machine)

> This task produces no code commit by default; it **validates and, if needed, corrects** the selectors from Task 2 against what LinkedIn actually serves your burner session. Re-run it whenever LinkedIn's DOM changes and the scraper returns empty results.

- [ ] **Step 1: Install the browser binary**

Run:

```bash
uv run playwright install chromium
```

- [ ] **Step 2: Log in once (persistent profile)**

Run:

```bash
uv run python -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); c=p.chromium.launch_persistent_context('.linkedin_profile', headless=False); pg=c.new_page(); pg.goto('https://www.linkedin.com/login'); input('Log in with your BURNER account, then press Enter...'); c.close(); p.stop()"
```

`.linkedin_profile/` is already ignored from Task 1; never commit a logged-in session.

- [ ] **Step 3: Save real HTML and compare to the fixtures**

Run a search in that window, then in a Python REPL (`uv run python`) capture the current page HTML:

```python
from playwright.sync_api import sync_playwright
p = sync_playwright().start()
c = p.chromium.launch_persistent_context(".linkedin_profile", headless=False)
pg = c.new_page()
pg.goto("https://www.linkedin.com/jobs/search/?keywords=backend%20engineer")
input("Scroll the results, then press Enter...")
open("tests/fixtures/linkedin/search_live.html", "w", encoding="utf-8").write(pg.content())
# open a job, then:
open("tests/fixtures/linkedin/job_live.html", "w", encoding="utf-8").write(pg.content())
c.close(); p.stop()
```

The `*_live.html` files are ignored. Before committing any fixture update, sanitize it down to the minimum stable DOM excerpt needed by the parser tests.

- [ ] **Step 4: Point the parser tests at the live fixtures and adjust selectors**

Run the parser over the live HTML:

```bash
uv run python -c "from resume_agent.discovery.scraper.parser import parse_search_cards; print(len(parse_search_cards(open('tests/fixtures/linkedin/search_live.html', encoding='utf-8').read())))"
```

If it prints `0`, the live DOM differs. Inspect `search_live.html`, update the CSS selectors in `parser.py` (e.g. the card container, title, subtitle, location, link), and re-run until cards are extracted. Repeat for `parse_job_detail` against `job_live.html`. Then update `tests/fixtures/linkedin/search.html` / `job.html` (or add `*_live`-derived fixtures) so Task 2's tests reflect the real structure.

- [ ] **Step 5: End-to-end dry run**

Run:

```bash
uv run resume-agent scrape --limit 3
```

Expected: "Added N new job(s)." Then `uv run resume-agent discover` should extract/filter/score them. If selectors changed, commit the parser + fixture updates:

```bash
git add src/resume_agent/discovery/scraper/parser.py tests/fixtures/linkedin/ tests/test_scraper_parser.py
git commit -m "fix(scraper): calibrate selectors against live LinkedIn HTML" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review (completed during plan authoring)

- **Spec coverage (§5.2):** LinkedIn scraper via Playwright with a persistent logged-in burner profile, human-like pacing, result cap (Task 4); result cards → detail pages → full JD text → `jobs(status=raw)` (Tasks 2–3); scraper behind an interface (`JobSource`) so parsing is testable against saved fixtures (Tasks 2–3); manual-assist fallback already shipped (`addjob`); clean/dedupe reused from `add_job` (Task 3). Risk #1 (DOM churn) addressed by the calibration loop (Task 6).
- **Placeholder scan:** none in the code tasks — complete parser, orchestrator, driver, and CLI with exact commands. Task 6 is explicitly a manual calibration procedure (not code with placeholders).
- **Type consistency:** `parse_search_cards(html: str) -> list[ScrapedCard]`, `parse_job_detail(html: str) -> str`; `JobSource.search(config) -> list[ScrapedCard]` + `fetch_jd(card) -> str` implemented by `LinkedInScraper` and the test's `_FakeSource`; `ingest_scraped(session, source, config, limit=None) -> int` matches the CLI call and the test stub; `add_job(...)` keyword args match `discovery/ingest.py`. CLI patches module-level `cli.load_search_config`, `cli.build_linkedin_scraper`, `cli.ingest_scraped`.

---

## Notes / future

- **v2 (memo):** add an Indeed `JobSource` implementing the same protocol; `ingest_scraped` is source-agnostic. Greenhouse/Lever/Ashby JSON endpoints would be far more stable sources behind the same interface.
- Consider persisting the raw card HTML on the job row (`extra`) for re-parsing after selector fixes without re-scraping.

## Execution Handoff

This is the last v1 component. After it is executed and calibrated, the full v1 pipeline runs end-to-end: `scrape → discover → approve → tailor → render → dashboard`. v2–v4 remain as the roadmap memo in the design spec (§10) and need their own brainstorming before planning.
