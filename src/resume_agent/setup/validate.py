from typing import Callable

from resume_agent.setup.preflight import CheckResult


def _default_anthropic_client(api_key: str):
    import anthropic

    from resume_agent.config import get_settings
    from resume_agent.llm_routing import direct_api_base_url

    return anthropic.Anthropic(
        api_key=api_key,
        base_url=direct_api_base_url("anthropic", get_settings()),
    )


def anthropic_ping(
    api_key: str,
    client_factory: Callable[[str], object] = _default_anthropic_client,
) -> CheckResult:
    """Confirm the key is accepted via a cheap models.list() call. Never raises."""
    try:
        client = client_factory(api_key)
        client.models.list()  # type: ignore[attr-defined]
        return CheckResult("anthropic", True, "Key accepted.")
    except Exception as exc:  # noqa: BLE001 — surface any failure as a CheckResult
        return CheckResult(
            "anthropic", False, str(exc), remedy="Check ANTHROPIC_API_KEY in .env."
        )


def connector_smoke(
    enabled: list[str], probe: Callable[[str], None]
) -> list[CheckResult]:
    """Run ``probe(name)`` per enabled connector; capture failures as results."""
    results: list[CheckResult] = []
    for name in enabled:
        try:
            probe(name)
            results.append(CheckResult(name, True, "Reachable."))
        except Exception as exc:  # noqa: BLE001
            results.append(CheckResult(name, False, str(exc)))
    return results
