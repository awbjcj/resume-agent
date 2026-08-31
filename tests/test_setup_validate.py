from resume_tailor_harness.setup.preflight import CheckResult
from resume_tailor_harness.setup.validate import anthropic_ping, connector_smoke


class _OkClient:
    class models:
        @staticmethod
        def list():
            return ["ok"]


def test_anthropic_ping_success_with_injected_factory():
    r = anthropic_ping("sk-test", client_factory=lambda key: _OkClient())
    assert isinstance(r, CheckResult)
    assert r.ok is True


def test_anthropic_ping_failure_is_captured_not_raised():
    def boom(key):
        raise RuntimeError("401 unauthorized")

    r = anthropic_ping("bad", client_factory=boom)
    assert r.ok is False
    assert "401" in r.detail


def test_connector_smoke_reports_per_connector():
    def probe(name):
        if name == "adzuna":
            raise RuntimeError("missing keys")

    results = connector_smoke(["remoteok", "adzuna"], probe=probe)
    by_name = {r.name: r.ok for r in results}
    assert by_name == {"remoteok": True, "adzuna": False}
