import resume_agent.discovery.url_ingest.browser as browser


class _FakePage:
    def __init__(self):
        self.goto_url = None
        self.waited_for = None

    def goto(self, url, wait_until=None):
        self.goto_url = url

    def wait_for_selector(self, selector, timeout=None):
        self.waited_for = (selector, timeout)
        return None

    def content(self):
        return "<html>rendered</html>"


class _FakeContext:
    def __init__(self, page):
        self._page = page
        self.closed = False

    def new_page(self):
        return self._page

    def close(self):
        self.closed = True


class _FakeChromium:
    def __init__(self, context):
        self._context = context
        self.data_dir = None

    def launch_persistent_context(self, data_dir, headless=False):
        self.data_dir = data_dir
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
        "https://job.test/x", user_data_dir="/tmp/p", pace_seconds=0.0
    )

    assert html == "<html>rendered</html>"
    assert page.goto_url == "https://job.test/x"
    assert chromium.data_dir == "/tmp/p"
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
    )

    assert page.waited_for == ("div.jd", 1234)
