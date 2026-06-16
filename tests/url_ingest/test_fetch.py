import resume_agent.discovery.url_ingest.fetch as fetch


class _Resp:
    def __init__(self, text, url):
        self.text = text
        self.url = url

    def raise_for_status(self):
        return None


def _patch_browser(monkeypatch, marker="<html>browser</html>"):
    calls = {}

    def fake_rendered(url, **kwargs):
        calls["url"] = url
        calls["wait_selector"] = kwargs.get("wait_selector")
        return marker

    monkeypatch.setattr(fetch, "fetch_rendered", fake_rendered)
    return calls


def test_static_page_uses_http(monkeypatch):
    body = "<html><body>" + "x " * 200 + "</body></html>"
    monkeypatch.setattr(
        fetch.httpx, "get", lambda url, **kw: _Resp(body, "https://boards.greenhouse.io/x")
    )
    browser_calls = _patch_browser(monkeypatch)

    page = fetch.fetch_page("https://boards.greenhouse.io/x")

    assert page.rendered is False
    assert "x x" in page.html
    assert browser_calls == {}


def test_linkedin_host_uses_browser(monkeypatch):
    monkeypatch.setattr(
        fetch.httpx, "get", lambda url, **kw: (_ for _ in ()).throw(AssertionError("no http"))
    )
    browser_calls = _patch_browser(monkeypatch)

    page = fetch.fetch_page("https://www.linkedin.com/jobs/view/123")

    assert page.rendered is True
    assert page.html == "<html>browser</html>"
    assert browser_calls["url"] == "https://www.linkedin.com/jobs/view/123"


def test_js_shell_falls_back_to_browser(monkeypatch):
    shell = "<html><body><div id='root'></div></body></html>"
    monkeypatch.setattr(
        fetch.httpx, "get", lambda url, **kw: _Resp(shell, "https://acme.test/job")
    )
    _patch_browser(monkeypatch)

    page = fetch.fetch_page("https://acme.test/job")

    assert page.rendered is True
    assert page.html == "<html>browser</html>"


def test_no_browser_flag_skips_fallback(monkeypatch):
    shell = "<html><body></body></html>"
    monkeypatch.setattr(
        fetch.httpx, "get", lambda url, **kw: _Resp(shell, "https://acme.test/job")
    )
    monkeypatch.setattr(
        fetch, "fetch_rendered", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no browser"))
    )

    page = fetch.fetch_page("https://acme.test/job", allow_browser=False)

    assert page.rendered is False
