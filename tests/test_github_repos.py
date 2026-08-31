import httpx
import pytest

from resume_tailor_harness.github.repos import RepoMeta, parse_github_url, verify_repo


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/kubernetes/kubernetes", ("kubernetes", "kubernetes")),
        ("http://github.com/foo/bar/", ("foo", "bar")),
        ("https://github.com/foo/bar/tree/main", ("foo", "bar")),
        ("https://github.com/foo/bar.git", ("foo", "bar")),
        ("https://example.com/foo/bar", None),
        ("https://github.com.evil.test/foo/bar", None),
        ("https://github.com/foo", None),
        ("javascript:alert(1)", None),
    ],
)
def test_parse_github_url(url, expected):
    assert parse_github_url(url) == expected


def test_verify_repo_returns_validated_metadata(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        return httpx.Response(
            200,
            json={
                "full_name": "foo/bar",
                "html_url": "https://github.com/foo/bar",
                "stargazers_count": 42,
                "description": "A repository",
            },
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    assert verify_repo("foo", "bar") == RepoMeta(
        "foo/bar",
        "https://github.com/foo/bar",
        42,
        "A repository",
    )


def test_verify_repo_returns_none_for_404(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        return httpx.Response(404, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)

    assert verify_repo("foo", "ghost") is None


def test_verify_repo_propagates_infrastructure_errors(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(httpx.HTTPError):
        verify_repo("foo", "bar")


def test_verify_repo_rejects_malformed_success_payload(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        return httpx.Response(
            200,
            json=["not", "an", "object"],
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(ValueError, match="object"):
        verify_repo("foo", "bar")
