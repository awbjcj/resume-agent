from datetime import datetime, timezone

from resume_agent.discovery.scraper.dashboard import DashboardScraper
from resume_agent.discovery.scraper.recipe import Pagination, ScrapeRecipe
from resume_agent.discovery.search_config import SearchConfig


class _Target:
    def __init__(self, url, *, enabled=True, label=None):
        self.url = url
        self.enabled = enabled
        self.label = label


def _recipe(**overrides):
    values = {
        "learned_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
        "card_container": "li.job",
        "jd_container": "div.jd",
        "title_sel": "a",
        "location_sel": "span.loc",
        "url_sel": "a",
        "detail_mode": "link",
        "pagination": Pagination(pattern="next", control_sel="a.next", max_pages=2),
    }
    values.update(overrides)
    return ScrapeRecipe(**values)


class _FakeAgent:
    def __init__(self, content):
        self.calls = 0
        self.content = content

    def run(self, prompt):
        self.calls += 1

        class _Response:
            pass

        response = _Response()
        response.content = self.content
        return response

    async def arun(self, prompt):
        return self.run(prompt)


_LIST = """<ul>
  <li class="job"><a href="/jobs/1">Backend Engineer</a><span class="loc">Remote</span></li>
  <li class="job"><a href="/jobs/2">Data Scientist</a><span class="loc">NYC</span></li>
</ul>"""

_THREE_JOBS = _LIST.replace(
    "</ul>",
    '<li class="job"><a href="/jobs/3">Platform Engineer</a>'
    '<span class="loc">Austin</span></li></ul>',
)

_DETAIL = "<div class='jd'><p>Python backend services and APIs for scale.</p></div>"


class _Scraper(DashboardScraper):
    """Every browser seam is stubbed; tests never launch Chromium."""

    def __init__(self, *, list_html=_LIST, **kwargs):
        super().__init__(**kwargs)
        self.list_html = list_html
        self.detail_urls = []
        self.open_calls = 0

    def _learn_source(self, target):
        return self.list_html

    def _open_results(self, target, search, recipe):
        self.open_calls += 1
        return self.list_html

    def _next_page(self, recipe):
        return None

    def _detail_html(self, card, recipe):
        self.detail_urls.append(card.url)
        return _DETAIL


def test_learns_once_then_resolves_urls_and_propagates_company_label(tmp_path):
    learner = _FakeAgent(_recipe())
    scraper = _Scraper(
        targets=[_Target("https://acme.com/careers", label="Acme")],
        store_dir=tmp_path,
        learn_agent=learner,
    )

    result = scraper.fetch(SearchConfig(role_anchors=["engineer"]))

    assert [job.title for job in result.jobs] == ["Backend Engineer"]
    assert result.jobs[0].url == "https://acme.com/jobs/1"
    assert result.jobs[0].company == "Acme"
    assert result.jobs[0].source == "scrape"
    assert result.jobs[0].jd_text.strip()
    assert learner.calls == 1


def test_second_pull_reuses_cached_recipe(tmp_path):
    learner = _FakeAgent(_recipe())
    target = _Target("https://acme.com/careers")
    for _ in range(2):
        _Scraper(targets=[target], store_dir=tmp_path, learn_agent=learner).fetch(
            SearchConfig()
        )
    assert learner.calls == 1


def test_skip_seen_receives_absolute_url_and_prunes_before_detail(tmp_path):
    scraper = _Scraper(
        targets=[_Target("https://acme.com/careers")],
        store_dir=tmp_path,
        learn_agent=_FakeAgent(_recipe()),
    )

    result = scraper.fetch(
        SearchConfig(),
        skip_seen=lambda row: row.url == "https://acme.com/jobs/1",
    )

    assert "https://acme.com/jobs/1" not in scraper.detail_urls
    assert {job.url for job in result.jobs} == {"https://acme.com/jobs/2"}


def test_limit_stops_additional_detail_fetches(tmp_path):
    scraper = _Scraper(
        list_html=_THREE_JOBS,
        targets=[_Target("https://acme.com/careers")],
        store_dir=tmp_path,
        learn_agent=_FakeAgent(_recipe()),
    )

    result = scraper.fetch(SearchConfig(), limit=1)

    assert len(result.jobs) == 1
    assert scraper.detail_urls == ["https://acme.com/jobs/1"]


def test_inline_recipe_parses_detail_without_navigation(tmp_path):
    inline_html = """
    <article class='job'><h2>Backend Engineer</h2><span class='loc'>Remote</span>
      <div class='jd'><p>Build Python services.</p></div>
    </article>
    """
    inline_recipe = _recipe(
        card_container="article.job",
        title_sel="h2",
        location_sel="span.loc",
        url_sel=None,
        detail_mode="inline",
        pagination=Pagination(pattern="infinite", max_pages=1),
    )
    scraper = _Scraper(
        list_html=inline_html,
        targets=[_Target("https://acme.com/careers", label="Acme")],
        store_dir=tmp_path,
        learn_agent=_FakeAgent(inline_recipe),
    )

    result = scraper.fetch(SearchConfig())

    assert len(result.jobs) == 1
    assert "Build Python services" in result.jobs[0].jd_text
    assert scraper.detail_urls == []


def test_disabled_target_is_not_opened(tmp_path):
    scraper = _Scraper(
        targets=[_Target("https://acme.com/careers", enabled=False)],
        store_dir=tmp_path,
        learn_agent=_FakeAgent(_recipe()),
    )
    assert scraper.fetch(SearchConfig()).jobs == []
    assert scraper.open_calls == 0


class _SequenceAgent(_FakeAgent):
    def __init__(self, *contents):
        super().__init__(None)
        self.contents = contents

    def run(self, prompt):
        content = self.contents[min(self.calls, len(self.contents) - 1)]
        self.calls += 1

        class _Response:
            pass

        response = _Response()
        response.content = content
        return response


def test_guarded_relearn_recollects_pages_once_when_recipe_misses_jobs(tmp_path):
    bad_recipe = _recipe(card_container="li.missing")
    learner = _SequenceAgent(bad_recipe, _recipe())
    scraper = _Scraper(
        list_html=_THREE_JOBS,
        targets=[_Target("https://acme.com/careers")],
        store_dir=tmp_path,
        learn_agent=learner,
    )

    result = scraper.fetch(SearchConfig())

    assert learner.calls == 2
    assert scraper.open_calls == 2
    assert result.jobs


class _FakeExtract(_FakeAgent):
    def __init__(self):
        from resume_agent.discovery.url_ingest.models import ExtractedJob

        super().__init__(
            ExtractedJob(
                company="Recovered Co",
                title="Recovered title must not replace deterministic title",
                location="Recovered location must not replace deterministic location",
                jd_text="Recovered JD body from raw page text.",
            )
        )


class _EmptyDetailScraper(_Scraper):
    def _detail_html(self, card, recipe):
        self.detail_urls.append(card.url)
        return "<main><p>Recovered JD body from raw page text.</p></main>"


def test_llm_fallback_recovers_empty_deterministic_detail_and_missing_fields(tmp_path):
    extractor = _FakeExtract()
    scraper = _EmptyDetailScraper(
        targets=[_Target("https://acme.com/careers")],
        store_dir=tmp_path,
        learn_agent=_FakeAgent(_recipe()),
        extract_agent=extractor,
    )

    result = scraper.fetch(SearchConfig(role_anchors=["engineer"]))

    assert len(result.jobs) == 1
    assert result.jobs[0].jd_text == "Recovered JD body from raw page text."
    assert result.jobs[0].company == "Recovered Co"
    assert result.jobs[0].title == "Backend Engineer"
    assert result.jobs[0].location == "Remote"
    assert extractor.calls == 1


def test_deterministic_detail_does_not_call_llm_fallback(tmp_path):
    extractor = _FakeExtract()
    scraper = _Scraper(
        targets=[_Target("https://acme.com/careers")],
        store_dir=tmp_path,
        learn_agent=_FakeAgent(_recipe()),
        extract_agent=extractor,
    )

    scraper.fetch(SearchConfig(), limit=1)

    assert extractor.calls == 0
