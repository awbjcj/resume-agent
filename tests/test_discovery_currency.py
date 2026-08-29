from resume_agent.discovery import currency


def test_usd_rate_for_reads_and_caches_frankfurter_quote(monkeypatch):
    calls: list[dict] = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return [{"base": "EUR", "quote": "USD", "rate": 1.08}]

    def get(url, *, params, timeout):
        calls.append({"url": url, "params": params, "timeout": timeout})
        return Response()

    monkeypatch.setattr(currency.httpx, "get", get)
    monkeypatch.setattr(
        currency,
        "_rates",
        {"USD": (1.0, currency.datetime.max.replace(tzinfo=currency.UTC))},
    )

    assert currency.usd_rate_for("eur") == 1.08
    assert currency.usd_rate_for("EUR") == 1.08
    assert calls == [
        {
            "url": "https://api.frankfurter.dev/v2/rates",
            "params": {"base": "EUR", "quotes": "USD"},
            "timeout": 5.0,
        }
    ]
