from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable, Protocol, Sequence
from urllib.parse import urljoin, urlsplit

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from resume_agent.discovery.connectors.base import FetchResult, RawJob
from resume_agent.discovery.connectors.text import (
    primary_search_term,
    relevance_gate,
    title_relevance_gate,
)
from resume_agent.discovery.scraper.learn import build_learn_agent, learn_recipe, prune_html
from resume_agent.discovery.scraper.models import ScrapedCard
from resume_agent.discovery.scraper.recipe import ScrapeRecipe
from resume_agent.discovery.scraper.recipe_parse import (
    has_job_like_content,
    parse_cards,
    parse_detail,
)
from resume_agent.discovery.scraper.recipe_store import (
    RECIPES_DIR,
    host_key,
    load_recipe,
    save_recipe,
)
from resume_agent.discovery.search_config import SearchConfig
from resume_agent.discovery.url_ingest.llm import (
    build_url_extract_agent,
    extract_fields,
    html_to_text,
)
from resume_agent.discovery.url_ingest.models import ExtractedJob
from resume_agent.llm_runner import Runner

_CONTENT_CHANGE_POLLS = 80
_CONTENT_CHANGE_POLL_MS = 100
_RESULT_WAIT_MS = 8_000
MAX_EXTRACT_CHARS = 60_000


class ScrapeTargetLike(Protocol):
    url: str
    enabled: bool
    label: str | None
    limit: int | None


SkipSeen = Callable[[RawJob], bool]


class DashboardScraper:
    """Replay learned selectors over explicitly configured company job boards."""

    name = "scrape"
    concurrent_fetch = False
    # Each posting detail costs a browser navigation (and possibly an LLM
    # extract), so ``fetch`` honours the runner-supplied ``skip_seen`` gate to
    # drop cards already held from a same-or-higher-priority source before doing
    # that detail work.

    def __init__(
        self,
        targets: Sequence[ScrapeTargetLike],
        *,
        store_dir: str | Path = RECIPES_DIR,
        learn_agent: Runner | None = None,
        extract_agent: Runner | None = None,
        relearn: bool = False,
        headless: bool = False,
        pace_seconds: float = 1.0,
    ) -> None:
        self.targets = list(targets)
        self.store_dir = store_dir
        self._learn_agent = learn_agent
        self._extract_agent = extract_agent
        self.relearn = relearn
        self.headless = headless
        self.pace_seconds = pace_seconds
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    def _learner(self) -> Runner:
        if self._learn_agent is None:
            self._learn_agent = build_learn_agent()
        return self._learn_agent

    def _extractor(self) -> Runner:
        if self._extract_agent is None:
            self._extract_agent = build_url_extract_agent()
        return self._extract_agent

    def _ensure_page(self) -> Page:
        if self._page is None:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=self.headless)
            self._context = self._browser.new_context()
            self._page = self._context.new_page()
        return self._page

    def _close_browser(self) -> None:
        for resource in (self._context, self._browser):
            if resource is None:
                continue
            try:
                resource.close()
            except Exception:  # noqa: BLE001 - cleanup must not mask a fetch result
                pass
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:  # noqa: BLE001 - cleanup must not mask a fetch result
                pass
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None

    def _page_source(self, url: str, wait_selector: str | None = None) -> str:
        page = self._ensure_page()
        page.goto(url, wait_until="domcontentloaded")
        if wait_selector:
            try:
                page.wait_for_selector(wait_selector, timeout=_RESULT_WAIT_MS)
            except PlaywrightTimeoutError:
                pass
        self._pace(page)
        return page.content()

    def _pace(self, page: Page) -> None:
        if self.pace_seconds > 0:
            page.wait_for_timeout(round(self.pace_seconds * 1_000))

    def _learn_source(self, target: ScrapeTargetLike) -> str:
        return self._page_source(target.url)

    def _open_results(
        self,
        target: ScrapeTargetLike,
        search: SearchConfig,
        recipe: ScrapeRecipe,
    ) -> str:
        page = self._ensure_page()
        page.goto(target.url, wait_until="domcontentloaded")
        term = primary_search_term(search)
        if recipe.search is not None and term:
            search_input = page.locator(recipe.search.input_sel)
            search_input.fill(term)
            if recipe.search.submit_sel:
                page.locator(recipe.search.submit_sel).click()
            else:
                search_input.press("Enter")
        try:
            page.wait_for_selector(recipe.card_container, timeout=_RESULT_WAIT_MS)
        except PlaywrightTimeoutError:
            pass
        self._pace(page)
        return page.content()

    @staticmethod
    def _card_signature(html: str, recipe: ScrapeRecipe) -> tuple[tuple[str | None, ...], ...]:
        return tuple(
            (card.url, card.title, card.location)
            for card in parse_cards(html, recipe)
            if card.title
        )

    def _changed_cards(
        self,
        before: tuple[tuple[str | None, ...], ...],
        recipe: ScrapeRecipe,
    ) -> str | None:
        page = self._page
        if page is None:
            return None
        for _ in range(_CONTENT_CHANGE_POLLS):
            after = page.content()
            signature = self._card_signature(after, recipe)
            if signature and signature != before:
                return after
            page.wait_for_timeout(_CONTENT_CHANGE_POLL_MS)
        return None

    def _next_page(self, recipe: ScrapeRecipe) -> str | None:
        page = self._page
        if page is None:
            return None
        before = self._card_signature(page.content(), recipe)
        try:
            if recipe.pagination.pattern == "infinite":
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            else:
                control = page.locator(recipe.pagination.control_sel or "").first
                if control.count() == 0:
                    return None
                control.click()
            return self._changed_cards(before, recipe)
        except PlaywrightError:
            return None

    def _detail_html(self, card: ScrapedCard, recipe: ScrapeRecipe) -> str:
        if card.url is None:
            return ""
        return self._page_source(card.url, recipe.jd_container)

    def _collect_pages(
        self,
        target: ScrapeTargetLike,
        search: SearchConfig,
        recipe: ScrapeRecipe,
    ) -> list[str]:
        pages = [self._open_results(target, search, recipe)]
        for _ in range(recipe.pagination.max_pages - 1):
            next_page = self._next_page(recipe)
            if next_page is None:
                break
            pages.append(next_page)
        return pages

    def _recipe_for(
        self,
        target: ScrapeTargetLike,
        search: SearchConfig,
    ) -> tuple[ScrapeRecipe, list[ScrapedCard]]:
        host = host_key(target.url)
        recipe = None if self.relearn else load_recipe(host, self.store_dir)
        if recipe is None:
            recipe = learn_recipe(prune_html(self._learn_source(target)), self._learner())
            save_recipe(host, recipe, self.store_dir)
        pages = self._collect_pages(target, search, recipe)
        cards = self._cards(recipe, pages, target.url)
        if not cards and has_job_like_content(pages[0]):
            # A cached recipe can miss because the board changed OR because this
            # search legitimately matched nothing; only adopt (and persist) the
            # relearned recipe when it actually yields cards, so a zero-result
            # search never clobbers a still-working recipe on disk.
            new_recipe = learn_recipe(prune_html(pages[0]), self._learner())
            new_pages = self._collect_pages(target, search, new_recipe)
            new_cards = self._cards(new_recipe, new_pages, target.url)
            if new_cards:
                save_recipe(host, new_recipe, self.store_dir)
                recipe, cards = new_recipe, new_cards
        return recipe, cards

    @staticmethod
    def _cards(
        recipe: ScrapeRecipe,
        pages: list[str],
        base_url: str,
    ) -> list[ScrapedCard]:
        seen: set[tuple[str | None, ...]] = set()
        cards: list[ScrapedCard] = []
        for html in pages:
            for parsed in parse_cards(html, recipe):
                if not parsed.title:
                    continue
                resolved_url = urljoin(base_url, parsed.url) if parsed.url else None
                if resolved_url and urlsplit(resolved_url).scheme not in {"http", "https"}:
                    resolved_url = None
                card = replace(
                    parsed,
                    url=resolved_url,
                )
                identity = (card.url,) if card.url else (None, card.title, card.location)
                if identity in seen:
                    continue
                seen.add(identity)
                cards.append(card)
        return cards

    def _detail_fields(self, card: ScrapedCard, recipe: ScrapeRecipe) -> ExtractedJob:
        html = card.detail_html if recipe.detail_mode == "inline" else self._detail_html(card, recipe)
        parsed = parse_detail(html or "", recipe).strip()
        if parsed:
            return ExtractedJob(jd_text=parsed)
        fallback_text = html_to_text(html or "")[:MAX_EXTRACT_CHARS]
        return extract_fields(fallback_text, self._extractor())

    def fetch(
        self,
        search: SearchConfig,
        limit: int | None = None,
        skip_seen: SkipSeen | None = None,
    ) -> FetchResult:
        jobs: list[RawJob] = []
        failures: dict[str, str] = {}
        filtered = 0
        if limit is not None and limit <= 0:
            return FetchResult(jobs=[])
        try:
            for target in self.targets:
                if not getattr(target, "enabled", True):
                    continue
                try:
                    recipe, cards = self._recipe_for(target, search)
                except Exception as exc:  # noqa: BLE001 - isolate configured targets
                    failures[target.url] = f"{type(exc).__name__}: {exc}"
                    continue

                target_limit = target.limit if target.limit is not None else limit
                taken = 0
                for card in cards:
                    if target_limit is not None and taken >= target_limit:
                        break
                    if recipe.detail_mode == "link" and card.url is None:
                        key = card.title or target.url
                        failures[key] = "Invalid or missing HTTP(S) detail URL"
                        continue
                    row = RawJob(
                        source="scrape",
                        url=card.url,
                        company=card.company or getattr(target, "label", None),
                        title=card.title,
                        location=card.location,
                        jd_text="",
                    )
                    if not title_relevance_gate([row], search):
                        filtered += 1
                        continue
                    if skip_seen is not None and skip_seen(row):
                        continue
                    key = card.url or card.title or target.url
                    try:
                        detail = self._detail_fields(card, recipe)
                    except Exception as exc:  # noqa: BLE001 - isolate posting details
                        failures[key] = f"{type(exc).__name__}: {exc}"
                        continue
                    row.jd_text = detail.jd_text.strip()
                    row.company = row.company or detail.company
                    row.title = row.title or detail.title
                    row.location = row.location or detail.location
                    if not row.jd_text:
                        continue
                    if not relevance_gate([row], search):
                        filtered += 1
                        continue
                    jobs.append(row)
                    taken += 1
            return FetchResult(jobs=jobs, failures=failures, filtered=filtered)
        finally:
            self._close_browser()


def build_dashboard_scraper(targets: Sequence[ScrapeTargetLike]) -> DashboardScraper:
    return DashboardScraper(targets)
