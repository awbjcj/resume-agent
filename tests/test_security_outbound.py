import httpx

from resume_agent.security.outbound import fetch_public_text


def test_fetch_public_text_retains_validated_redirect_provenance():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/careers"})
        return httpx.Response(200, headers={"content-type": "text/html"}, text="Careers")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = fetch_public_text(
            "https://example.com/start",
            client=client,
            resolver=lambda host: {"93.184.216.34"},
        )
    finally:
        client.close()

    assert seen == ["/start", "/careers"]
    assert result.final_url == "https://example.com/careers"
    assert result.redirect_chain == (
        "https://example.com/start",
        "https://example.com/careers",
    )
