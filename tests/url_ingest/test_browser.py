from typing import Any, cast

import pytest
from playwright.sync_api import Error as PlaywrightError

import resume_agent.discovery.url_ingest.browser as browser


class _FakePage:
    def __init__(self):
        self.goto_url = None
        self.url = None
        self.waited_for = None

    def goto(self, url, wait_until=None):
        self.goto_url = url
        self.url = url

    def wait_for_selector(self, selector, timeout=None):
        self.waited_for = (selector, timeout)
        return None

    def content(self):
        return "<html>rendered</html>"


class _FakeContext:
    def __init__(self, page):
        self._page = page
        self.closed = False
        self.routes = []

    def new_page(self):
        return self._page

    def route(self, pattern, handler):
        self.routes.append((pattern, handler))

    def close(self):
        self.closed = True


class _FakeChromium:
    def __init__(self, context):
        self._context = context
        self.data_dir = None

    def launch_persistent_context(self, data_dir, headless=False, **kwargs):
        self.data_dir = data_dir
        self.launch_kwargs = kwargs
        return self._context


class _FakePlaywright:
    def __init__(self, chromium):
        self.chromium = chromium

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_fetch_rendered_navigates_and_returns_content(monkeypatch):
    page = _FakePage()
    context = _FakeContext(page)
    chromium = _FakeChromium(context)
    monkeypatch.setattr(browser, "sync_playwright", lambda: _FakePlaywright(chromium))

    html = browser.fetch_rendered(
        "https://job.test/x",
        user_data_dir="/tmp/p",
        pace_seconds=0.0,
        resolver=lambda _host: {"93.184.216.34"},
    )

    assert html == "<html>rendered</html>"
    assert page.goto_url == "https://job.test/x"
    assert chromium.data_dir == "/tmp/p"
    assert chromium.launch_kwargs["service_workers"] == "block"
    assert context.routes[0][0] == "**/*"
    assert context.closed is True


def test_fetch_rendered_waits_for_selector(monkeypatch):
    page = _FakePage()
    context = _FakeContext(page)
    chromium = _FakeChromium(context)
    monkeypatch.setattr(browser, "sync_playwright", lambda: _FakePlaywright(chromium))

    browser.fetch_rendered(
        "https://job.test/x",
        user_data_dir="/tmp/p",
        wait_selector="div.jd",
        render_timeout_ms=1234,
        pace_seconds=0.0,
        resolver=lambda _host: {"93.184.216.34"},
    )

    assert page.waited_for == ("div.jd", 1234)


class _RedirectPage:
    """A page whose ``url`` resolves to a post-redirect destination after goto."""

    def __init__(self, destinations):
        self._destinations = destinations
        self.url = None
        self.closed = False

    def goto(self, url, wait_until=None, timeout=None):
        dest = self._destinations.get(url)
        if dest is None:
            raise RuntimeError(f"blocked: {url}")
        self.url = dest

    def wait_for_timeout(self, ms):
        return None

    def content(self):
        return f"<html>{self.url}</html>"

    def close(self):
        self.closed = True


class _MultiPageContext:
    def __init__(self, destinations):
        self._destinations = destinations
        self.pages = []
        self.closed = False
        self.routes = []

    def new_page(self):
        page = _RedirectPage(self._destinations)
        self.pages.append(page)
        return page

    def route(self, pattern, handler):
        self.routes.append((pattern, handler))

    def close(self):
        self.closed = True


def test_render_pages_captures_final_url_and_isolates_failures(monkeypatch):
    destinations = {
        "https://www.adzuna.com/land/ad/1": "https://www.dice.com/job-detail/1",
        # ad 2 has no destination -> goto raises -> omitted from results
    }
    context = _MultiPageContext(destinations)
    chromium = _FakeChromium(context)
    monkeypatch.setattr(browser, "sync_playwright", lambda: _FakePlaywright(chromium))

    pages = browser.render_pages(
        [
            "https://www.adzuna.com/land/ad/1",
            "https://www.adzuna.com/land/ad/2",
            "https://www.adzuna.com/land/ad/1",  # duplicate -> rendered once
        ],
        user_data_dir="/tmp/p",
        settle_ms=0,
        pace_seconds=0.0,
        resolver=lambda _host: {"93.184.216.34"},
    )

    assert set(pages) == {"https://www.adzuna.com/land/ad/1"}
    result = pages["https://www.adzuna.com/land/ad/1"]
    assert result.final_url == "https://www.dice.com/job-detail/1"
    assert result.rendered is True
    assert result.html == "<html>https://www.dice.com/job-detail/1</html>"
    # one page per distinct url (dedup), each closed; context closed.
    assert len(context.pages) == 2
    assert all(page.closed for page in context.pages)
    assert context.closed is True


def test_render_pages_empty_urls_skips_browser(monkeypatch):
    monkeypatch.setattr(
        browser,
        "sync_playwright",
        lambda: (_ for _ in ()).throw(AssertionError("no browser")),
    )
    assert browser.render_pages([]) == {}


class _FlakyChromium:
    """Fails the first launch with a PlaywrightError, then succeeds."""

    def __init__(self, context):
        self._context = context
        self.calls = 0

    def launch_persistent_context(self, data_dir, headless=False, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise PlaywrightError(
                "BrowserType.launch_persistent_context: Target page, "
                "context or browser has been closed"
            )
        return self._context


class _AlwaysFailsChromium:
    def __init__(self, message="boom"):
        self.calls = 0
        self._message = message

    def launch_persistent_context(self, data_dir, headless=False, **kwargs):
        self.calls += 1
        raise PlaywrightError(self._message)


def test_fetch_rendered_retries_after_clearing_stale_profile_cache(
    monkeypatch, tmp_path
):
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "GPUPersistentCache").mkdir()
    (profile / f"{profile.name}.CHROME_DELETE").mkdir()

    page = _FakePage()
    context = _FakeContext(page)
    chromium = _FlakyChromium(context)
    monkeypatch.setattr(browser, "sync_playwright", lambda: _FakePlaywright(chromium))

    html = browser.fetch_rendered(
        "https://job.test/x",
        user_data_dir=str(profile),
        pace_seconds=0.0,
        resolver=lambda _host: {"93.184.216.34"},
    )

    assert html == "<html>rendered</html>"
    assert chromium.calls == 2
    assert not (profile / "GPUPersistentCache").exists()
    assert not (profile / f"{profile.name}.CHROME_DELETE").exists()


def test_fetch_rendered_reraises_launch_failure_without_migration_artifacts(
    monkeypatch, tmp_path
):
    profile = tmp_path / "profile"
    profile.mkdir()
    chromium = _AlwaysFailsChromium()
    monkeypatch.setattr(browser, "sync_playwright", lambda: _FakePlaywright(chromium))

    with pytest.raises(PlaywrightError):
        browser.fetch_rendered(
            "https://job.test/x",
            user_data_dir=str(profile),
            pace_seconds=0.0,
            resolver=lambda _host: {"93.184.216.34"},
        )

    assert chromium.calls == 1


def test_fetch_rendered_reraises_when_retry_also_fails(monkeypatch, tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "ShaderCache").mkdir()
    chromium = _AlwaysFailsChromium("still broken")
    monkeypatch.setattr(browser, "sync_playwright", lambda: _FakePlaywright(chromium))

    with pytest.raises(PlaywrightError, match="still broken"):
        browser.fetch_rendered(
            "https://job.test/x",
            user_data_dir=str(profile),
            pace_seconds=0.0,
            resolver=lambda _host: {"93.184.216.34"},
        )

    assert chromium.calls == 2


class _FakeRequest:
    def __init__(self, url):
        self.url = url


class _FakeRoute:
    def __init__(self, url):
        self.request = _FakeRequest(url)
        self.action = None

    def abort(self, reason=None):
        self.action = ("abort", reason)

    def continue_(self):
        self.action = ("continue", None)


def test_public_request_guard_blocks_private_subresources():
    blocked = []
    route = _FakeRoute("http://169.254.169.254/latest/meta-data")

    browser._guard_public_request(
        cast(Any, route),
        resolver=lambda _host: {"169.254.169.254"},
        blocked=blocked,
    )

    assert route.action == ("abort", "blockedbyclient")
    assert len(blocked) == 1


def test_public_request_guard_continues_public_requests():
    blocked = []
    route = _FakeRoute("https://cdn.example.com/app.js")

    browser._guard_public_request(
        cast(Any, route),
        resolver=lambda _host: {"93.184.216.34"},
        blocked=blocked,
    )

    assert route.action == ("continue", None)
    assert blocked == []


def test_render_pages_omits_private_redirect_destination(monkeypatch):
    context = _MultiPageContext(
        {"https://public.example/start": "http://127.0.0.1/private"}
    )
    chromium = _FakeChromium(context)
    monkeypatch.setattr(browser, "sync_playwright", lambda: _FakePlaywright(chromium))

    pages = browser.render_pages(
        ["https://public.example/start"],
        user_data_dir="/tmp/p",
        settle_ms=0,
        pace_seconds=0.0,
        resolver=lambda host: {"127.0.0.1" if host == "127.0.0.1" else "93.184.216.34"},
    )

    assert pages == {}
