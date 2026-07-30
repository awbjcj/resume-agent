import httpx
import pytest

import resume_agent.discovery.url_ingest.fetch as fetch
from resume_agent.security.outbound import PublicTextResponse


def _public(text, url):
    return PublicTextResponse(final_url=url, text=text, content_type="text/html")


def _patch_browser(monkeypatch, marker="<html>browser</html>"):
    calls = {}
    monkeypatch.setattr(fetch, "validate_public_url", lambda _url: None)

    def fake_rendered(url, **kwargs):
        calls["url"] = url
        calls["wait_selector"] = kwargs.get("wait_selector")
        return marker

    monkeypatch.setattr(fetch, "fetch_rendered", fake_rendered)
    return calls


def test_static_page_uses_http(monkeypatch):
    body = "<html><body>" + "x " * 200 + "</body></html>"
    monkeypatch.setattr(
        fetch,
        "fetch_public_text",
        lambda url, **kw: _public(body, "https://boards.greenhouse.io/x"),
    )
    browser_calls = _patch_browser(monkeypatch)

    page = fetch.fetch_page("https://boards.greenhouse.io/x")

    assert page.rendered is False
    assert "x x" in page.html
    assert browser_calls == {}


def test_linkedin_host_uses_browser(monkeypatch):
    monkeypatch.setattr(
        fetch,
        "fetch_public_text",
        lambda url, **kw: (_ for _ in ()).throw(AssertionError("no http")),
    )
    browser_calls = _patch_browser(monkeypatch)

    page = fetch.fetch_page("https://www.linkedin.com/jobs/view/123")

    assert page.rendered is True
    assert page.html == "<html>browser</html>"
    assert browser_calls["url"] == "https://www.linkedin.com/jobs/view/123"
    assert browser_calls["wait_selector"] == fetch._LINKEDIN_DETAIL_SELECTOR


def test_js_shell_falls_back_to_browser(monkeypatch):
    shell = "<html><body><div id='root'></div></body></html>"
    monkeypatch.setattr(
        fetch,
        "fetch_public_text",
        lambda url, **kw: _public(shell, "https://acme.test/job"),
    )
    _patch_browser(monkeypatch)

    page = fetch.fetch_page("https://acme.test/job")

    assert page.rendered is True
    assert page.html == "<html>browser</html>"


def test_no_browser_flag_skips_fallback(monkeypatch):
    shell = "<html><body></body></html>"
    monkeypatch.setattr(
        fetch,
        "fetch_public_text",
        lambda url, **kw: _public(shell, "https://acme.test/job"),
    )
    monkeypatch.setattr(
        fetch,
        "fetch_rendered",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no browser")),
    )

    page = fetch.fetch_page("https://acme.test/job", allow_browser=False)

    assert page.rendered is False


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1/private", "http://169.254.169.254/metadata"],
)
def test_static_fetch_rejects_non_public_destinations_without_request(url):
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, text="not reached")

    http = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="public HTTP"):
        fetch.fetch_static(url, client=http)
    assert calls == 0
    http.close()


def test_static_fetch_revalidates_redirect_destinations():
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(302, headers={"location": "http://10.0.0.1/private"})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="public HTTP"):
        fetch.fetch_static(
            "https://example.com/start",
            client=http,
            resolver=lambda _host: {"93.184.216.34"},
        )
    assert calls == 1
    http.close()
