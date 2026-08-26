import httpx

from resume_agent.api.password_policy import HibpBreachChecker


def test_hibp_checker_uses_only_the_sha1_range_prefix(monkeypatch):
    password = "Correct-Horse-Battery-Staple"
    digest = "55408711BA54DBDD2C8FA7D4B2B9F45F7826CD42"
    seen: dict[str, object] = {}

    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        seen["url"] = url
        seen["headers"] = kwargs["headers"]
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            text=f"{digest[5:]}:3\n",
        )

    monkeypatch.setattr("resume_agent.api.password_policy.httpx.get", fake_get)

    assert HibpBreachChecker().is_breached(password) is True
    assert seen["url"] == f"https://api.pwnedpasswords.com/range/{digest[:5]}"
    assert seen["headers"] == {"Add-Padding": "true"}
