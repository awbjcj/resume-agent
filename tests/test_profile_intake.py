import httpx
import pytest

from resume_agent.profile.corpus import add_source, doc_path, load_manifest
from resume_agent.profile.intake import add_note_source, add_url_source


def public_ips(_host: str) -> set[str]:
    return {"93.184.216.34"}


def profile(tmp_path):
    resume = tmp_path / "resume.txt"
    resume.write_text("resume", encoding="utf-8")
    profile_dir = tmp_path / "profile"
    add_source(profile_dir, resume, primary=True)
    return profile_dir


def test_add_note_source_is_literal_and_validated(tmp_path):
    profile_dir = profile(tmp_path)
    document = add_note_source(
        profile_dir, "On-call lead", "Led the on-call rotation for 2 years."
    )
    assert document.filename == "note--on-call-lead.md"
    assert document.mode == "literal" and document.origin == "upload"
    assert "on-call rotation" in doc_path(profile_dir, document).read_text("utf-8")
    with pytest.raises(ValueError, match="empty"):
        add_note_source(profile_dir, "x", "  ")


def test_add_url_source_follows_public_redirect_and_records_provenance(tmp_path):
    profile_dir = profile(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(
                302, headers={"location": "https://example.com/final"}
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text="<title>My Portfolio</title><p>Built a rendering engine in Rust.</p>",
        )

    http = httpx.Client(transport=httpx.MockTransport(handler))
    document = add_url_source(
        profile_dir,
        "https://example.com/start",
        client=http,
        resolver=public_ips,
    )
    saved = doc_path(profile_dir, document).read_text("utf-8")
    assert document.filename == "url--my-portfolio.md"
    assert "rendering engine in Rust" in saved
    assert "https://example.com/final" in saved
    http.close()


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1/admin",
        "http://169.254.169.254/latest/meta-data",
        "http://user:password@example.com/private",
    ],
)
def test_add_url_source_rejects_unsafe_targets_without_request(tmp_path, url):
    profile_dir = profile(tmp_path)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, text="should not be fetched")

    http = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="public HTTP"):
        add_url_source(profile_dir, url, client=http, resolver=public_ips)
    assert calls == 0
    assert len(load_manifest(profile_dir).docs) == 1
    http.close()


def test_add_url_source_pins_the_validated_address_against_dns_rebinding(tmp_path):
    """The real request must hit the resolver's validated IP, never re-resolve
    the hostname — otherwise a second (attacker-controlled) DNS answer for the
    same hostname could rebind the connection to a private address after the
    public-IP check already passed."""
    profile_dir = profile(tmp_path)
    seen_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_hosts.append(request.url.host)
        assert request.headers["host"] == "example.com"
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<title>Pinned</title><p>Body text.</p>",
        )

    http = httpx.Client(transport=httpx.MockTransport(handler))
    add_url_source(
        profile_dir, "https://example.com/page", client=http, resolver=public_ips
    )
    assert seen_hosts == ["93.184.216.34"]
    http.close()


def test_add_url_source_rejects_redirect_to_private_address(tmp_path):
    profile_dir = profile(tmp_path)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(302, headers={"location": "http://10.0.0.1/secret"})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="public HTTP"):
        add_url_source(
            profile_dir,
            "https://example.com/start",
            client=http,
            resolver=public_ips,
        )
    assert calls == 1
    assert len(load_manifest(profile_dir).docs) == 1
    http.close()


def test_add_url_source_rejects_binary_oversized_and_empty_pages(tmp_path):
    profile_dir = profile(tmp_path)
    responses = iter(
        [
            httpx.Response(200, headers={"content-type": "image/png"}, content=b"png"),
            httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=b"x" * (1_000_001),
            ),
            httpx.Response(
                200, headers={"content-type": "text/html"}, text="<html></html>"
            ),
        ]
    )
    http = httpx.Client(transport=httpx.MockTransport(lambda _request: next(responses)))
    for message in ("content type", "too large", "no readable text"):
        with pytest.raises(ValueError, match=message):
            add_url_source(
                profile_dir,
                "https://example.com/page",
                client=http,
                resolver=public_ips,
            )
    assert len(load_manifest(profile_dir).docs) == 1
    http.close()


def test_add_url_source_stops_streaming_at_the_response_limit(tmp_path):
    profile_dir = profile(tmp_path)

    class CountingStream(httpx.SyncByteStream):
        def __init__(self):
            self.yielded = 0

        def __iter__(self):
            for _ in range(3):
                self.yielded += 1
                yield b"x" * 600_000

    stream = CountingStream()
    http = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"content-type": "text/plain"},
                stream=stream,
            )
        )
    )

    with pytest.raises(ValueError, match="too large"):
        add_url_source(
            profile_dir,
            "https://example.com/large",
            client=http,
            resolver=public_ips,
        )

    assert stream.yielded == 2
    http.close()


def test_note_source_uses_pinned_synthesis_only_when_an_owner_anchor_is_given(tmp_path):
    from resume_agent.profile.corpus import add_source
    from resume_agent.profile.intake import add_note_source

    resume = tmp_path / "resume.txt"
    resume.write_text("Ada", encoding="utf-8")
    add_source(tmp_path, resume, primary=True)
    anchored = add_note_source(
        tmp_path, "Acme", "I cut deploy time.", anchor="exp-acme"
    )
    unanchored = add_note_source(tmp_path, "Other", "I wrote a tool.")

    assert (anchored.mode, anchored.anchor) == ("synthesis", "exp-acme")
    assert (unanchored.mode, unanchored.anchor) == ("literal", None)
