"""Source Manager use-case layer over connectors.yaml."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from ipaddress import ip_address
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit

import yaml

from resume_agent.config import Settings, get_settings
from resume_agent.discovery.connectors.companies import CompaniesConnector
from resume_agent.discovery.connectors.config import (
    AshbyBoard as AshbyBoard,
    CompanyUrl as CompanyUrl,
    ConnectorsConfig,
    GreenhouseBoard,
    LeverBoard,
    NativeUrlBoard as NativeUrlBoard,
    ScrapeTarget as ScrapeTarget,
    load_connectors_config,
)
from resume_agent.discovery.connectors.detect import (
    AtsTarget,
    detect_ats,
    identify_host,
    inspect_ats,
)
from resume_agent.discovery.connectors.greenhouse import GreenhouseConnector
from resume_agent.discovery.connectors.lever import LeverConnector
from resume_agent.discovery.connectors.registry import (
    ConnectorSpec,
    find_unit,
    spec_for,
)
from resume_agent.discovery.source_resolution.catalog import canonical_target_url
from resume_agent.discovery.connectors.sources import (
    NATIVE_URL_KINDS as NATIVE_URL_KINDS,
    SourceView,
    company_url_id as company_url_id,
    list_source_views,
    native_url_id as native_url_id,
    scrape_target_id as scrape_target_id,
)
from resume_agent.discovery.search_config import SearchConfig, load_search_config
from resume_agent.security.outbound import resolve_host as _resolve_host
from resume_agent.services.discovery import DEFAULT_CONNECTORS, DEFAULT_SEARCH
from resume_agent.tenancy.paths import resolve_tenant_path

_PREVIEW_LIMIT = 50
_UNSET = object()
_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_HOST_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*$")

_SUBDOMAIN_PROVIDERS = {"recruitee", "personio", "breezy", "jazzhr", "bamboohr"}


class SourceError(Exception):
    """A source mutation the user can fix: unknown, duplicate, or invalid source."""


@dataclass(frozen=True)
class SourcePreview:
    ok: bool
    url: str
    kind: str | None = None
    token: str | None = None
    label: str | None = None
    role_count: int | None = None
    error: str | None = None
    error_code: str | None = None
    observed_companies: tuple[str, ...] = ()


def _save(path: str, config: ConnectorsConfig) -> None:
    target = resolve_tenant_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as stream:
        yaml.safe_dump(
            config.model_dump(mode="python"),
            stream,
            sort_keys=False,
            allow_unicode=True,
        )
    os.replace(tmp, target)


def list_sources(
    connectors_path: str = DEFAULT_CONNECTORS,
    settings: Settings | None = None,
) -> list[SourceView]:
    config = load_connectors_config(connectors_path)
    return list_source_views(config, settings or get_settings())


def _view(config: ConnectorsConfig, source_id: str) -> SourceView:
    offline_settings = Settings.model_construct()
    for view in list_source_views(config, offline_settings):
        if view.id == source_id:
            return view
    raise SourceError(f"Unknown source '{source_id}'")


def _preview_connector(target: AtsTarget, url: str, *, browser: bool = True):
    if target.ats == "greenhouse" and target.token:
        return GreenhouseConnector([GreenhouseBoard(token=target.token)])
    if target.ats == "lever" and target.token:
        return LeverConnector([LeverBoard(token=target.token)])
    return CompaniesConnector([url], browser_enabled=browser)


def _scrape_url(url: str | None) -> str:
    """Validate and normalize a user-supplied browser target.

    A hostname (as opposed to a literal IP) must resolve to only globally
    routable addresses — the same DNS-rebinding-aware check
    ``profile.intake._resolve_host`` applies to note/URL intake — otherwise an
    attacker-controlled or misconfigured domain could point the real,
    visible-browser scraper at an internal-only service.
    """
    raw = (url or "").strip()
    try:
        parsed = urlsplit(raw)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise SourceError("A scrape target must be a public HTTP(S) URL.") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise SourceError("A scrape target must be a public HTTP(S) URL.")
    normalized_host = host.casefold().rstrip(".")
    if normalized_host == "localhost" or normalized_host.endswith(".localhost"):
        raise SourceError("A scrape target must be a public HTTP(S) URL.")
    try:
        addresses = {str(ip_address(normalized_host))}
    except ValueError:
        try:
            addresses = _resolve_host(normalized_host)
        except OSError as exc:
            raise SourceError(
                f"Could not resolve scrape target host {normalized_host!r}."
            ) from exc
    if not addresses or any(not ip_address(addr).is_global for addr in addresses):
        raise SourceError("A scrape target must be a public HTTP(S) URL.")
    default_port = (parsed.scheme == "http" and port == 80) or (
        parsed.scheme == "https" and port == 443
    )
    netloc = (
        normalized_host if port is None or default_port else f"{normalized_host}:{port}"
    )
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme, netloc, path, parsed.query, ""))


_TRACKING_PARAMS = frozenset(
    {
        "fbclid",
        "gclid",
        "msclkid",
        "ref",
        "referrer",
        "trk",
        "trackingid",
    }
)


def _strip_tracking(url: str) -> str:
    """Drop analytics query parameters an agent copied along with a search result."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return url
    if not parsed.query:
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    kept = [
        pair
        for pair in parsed.query.split("&")
        if pair
        and not (
            (key := pair.split("=", 1)[0].casefold()).startswith("utm_")
            or key in _TRACKING_PARAMS
        )
    ]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "&".join(kept), ""))


def board_root_url(url: str) -> str:
    """Reduce a posting URL to the durable board root its ATS is addressed by.

    A single posting expires; the board root keeps returning new roles, so a
    stored source must never be a job-detail URL. This is deterministic rather
    than prompt-enforced because a proposal that slips through gets written into
    ``connectors.yaml`` and 404s on every later pull.

    ``identify_host`` is pure (no network) and already discards the parts that
    make a posting URL specific -- the Workday ``/job/...`` tail and its
    ``/en-US/`` locale segment, the Greenhouse ``/jobs/{id}`` tail, the Lever
    and Ashby posting ids. Rebuilding from the identity it returns therefore
    yields the same canonical URL the Source Manager's provider-native path
    produces. A URL behind no recognized ATS is returned unchanged apart from
    tracking parameters, because there is no board shape to reduce it to.
    """
    raw = _strip_tracking((url or "").strip())
    target = identify_host(raw)
    if target is None:
        return raw
    try:
        if not target.token:
            if (
                target.ats == "workday"
                and target.tenant
                and target.datacenter
                and target.site
            ):
                return _connection_url(
                    provider="workday",
                    tenant=target.tenant,
                    datacenter=target.datacenter,
                    site=target.site,
                )
            # Singleton portals (Tesla, Google Careers) are identified by host
            # alone, so there is no token to rebuild a root from.
            return raw
        return _connection_url(
            provider=target.ats,
            token=target.token,
            country=target.country,
        )
    except SourceError:
        # A slug the templates would reject is not a reason to lose the
        # proposal; the probe still gets the URL the agent actually found.
        return raw
    return raw


def _connection_url(
    *,
    provider: str,
    url: str | None = None,
    token: str | None = None,
    tenant: str | None = None,
    datacenter: str | None = None,
    site: str | None = None,
    country: str = "com",
) -> str:
    """Turn a provider-native connection recipe into its canonical public board URL."""
    if provider == "auto":
        normalized = (url or "").strip()
        if not normalized.startswith(("https://", "http://")):
            raise SourceError("Enter an absolute http(s) careers URL.")
        return normalized

    if provider == "workday":
        parts = {
            "tenant": (tenant or "").strip(),
            "datacenter": (datacenter or "").strip(),
            "site": (site or "").strip(),
        }
        if not all(parts.values()):
            raise SourceError("Workday requires tenant, data center, and career site.")
        if not _HOST_SLUG.fullmatch(parts["tenant"]) or not _HOST_SLUG.fullmatch(
            parts["datacenter"]
        ):
            raise SourceError("Workday tenant and data center must be URL-safe slugs.")
        if not _SLUG.fullmatch(parts["site"]):
            raise SourceError("Workday career site must be a URL-safe path segment.")
        return (
            f"https://{parts['tenant']}.{parts['datacenter']}.myworkdayjobs.com/"
            f"{parts['site']}"
        )

    normalized_token = (token or "").strip()
    token_pattern = _HOST_SLUG if provider in _SUBDOMAIN_PROVIDERS else _SLUG
    if not token_pattern.fullmatch(normalized_token):
        allowed = "letters, numbers, and hyphens"
        if provider not in _SUBDOMAIN_PROVIDERS:
            allowed += " or underscores"
        raise SourceError(f"Company token must contain only {allowed}.")
    if provider == "personio" and country not in {"com", "de"}:
        raise SourceError("Personio country must be com or de.")
    canonical = canonical_target_url(
        AtsTarget(provider, token=normalized_token, country=country)
    )
    if canonical is None:
        raise SourceError(f"Unknown source provider '{provider}'.")
    return canonical


def preview_source(
    url: str | None = None,
    label: str | None = None,
    search_path: str = DEFAULT_SEARCH,
    provider: str = "auto",
    token: str | None = None,
    tenant: str | None = None,
    datacenter: str | None = None,
    site: str | None = None,
    country: str = "com",
    limit: int = _PREVIEW_LIMIT,
    browser: bool = True,
    apply_search_filters: bool = True,
) -> SourcePreview:
    """Inspect a source and return a bounded job/company preview.

    Source Manager previews use the configured relevance filters by default.
    Ownership verification disables them so a valid board cannot lose its
    provider identity merely because none of its current roles match the user's
    job search.
    """
    if provider == "scrape":
        try:
            normalized = _scrape_url(url)
        except SourceError as exc:
            return SourcePreview(
                ok=False,
                url=url or "",
                kind="scrape",
                error=str(exc),
                error_code="INVALID_URL",
            )
        if not get_settings().browser_enabled:
            return SourcePreview(
                ok=False,
                url=normalized,
                kind="scrape",
                error="Scrape targets require a local browser.",
                error_code="BROWSER_REQUIRED",
            )
        return SourcePreview(ok=True, url=normalized, kind="scrape", label=label)

    try:
        resolved_url = _connection_url(
            provider=provider,
            url=url,
            token=token,
            tenant=tenant,
            datacenter=datacenter,
            site=site,
            country=country,
        )
    except SourceError as exc:
        return SourcePreview(ok=False, url=url or "", error=str(exc))

    inspection = inspect_ats(resolved_url)
    target = inspection.target
    if target is None:
        error_code = "ATS_NOT_DETECTED" if inspection.reachable else "UNREACHABLE"
        message = (
            "Could not detect a known ATS behind this URL."
            if inspection.reachable
            else "Could not reach this source."
        )
        return SourcePreview(
            ok=False,
            url=resolved_url,
            error=message,
            error_code=error_code,
        )
    if provider != "auto" and target.ats != provider:
        return SourcePreview(
            ok=False,
            url=resolved_url,
            kind=target.ats,
            error=f"The connection resolved as {target.ats}, not {provider}.",
        )

    try:
        search = (
            load_search_config(search_path) if apply_search_filters else SearchConfig()
        )
        result = _preview_connector(target, resolved_url, browser=browser).fetch(
            search,
            limit=limit,
        )
    except Exception as exc:  # noqa: BLE001 - preview returns errors instead of raising.
        return SourcePreview(
            ok=False,
            url=resolved_url,
            kind=target.ats,
            token=target.token or None,
            error=f"Could not reach this source: {type(exc).__name__}",
            error_code="UNREACHABLE",
        )

    if result.failures and not result.jobs:
        reason = "; ".join(result.failures.values())
        return SourcePreview(
            ok=False,
            url=resolved_url,
            kind=target.ats,
            token=target.token or None,
            error=reason,
            error_code="UNREACHABLE",
        )

    return SourcePreview(
        ok=True,
        url=resolved_url,
        kind=target.ats,
        token=target.token or None,
        label=label,
        role_count=len(result.jobs),
        observed_companies=tuple(
            dict.fromkeys(
                job.company.strip()
                for job in result.jobs
                if job.company_provenance == "provider"
                and job.company
                and job.company.strip()
            )
        ),
    )


def _duplicate_message(spec: ConnectorSpec, payload: Any) -> str:
    if spec.kind == "companies":
        return "This URL is already a source."
    if spec.kind == "scrape":
        return "This URL is already a scrape target."
    token = getattr(payload, "token", "")
    if token:
        return f"{spec.kind.title()} board '{token}' is already a source."
    return f"This {spec.kind.title()} board is already a source."


def _append_unit(
    config: ConnectorsConfig,
    spec: ConnectorSpec,
    *,
    target: AtsTarget | None,
    url: str,
    label: str | None,
) -> str:
    """Append one new unit through the spec table; return its source id."""
    if spec.new_unit is None or spec.unit_items is None or not spec.admits(target):
        raise SourceError(f"Sources of kind '{spec.kind}' cannot be added.")
    source_id, payload = spec.new_unit(target, url, label)
    if any(unit.source_id == source_id for unit in spec.units(config)):
        raise SourceError(_duplicate_message(spec, payload))
    spec.section(config).enabled = True
    spec.unit_items(config).append(payload)
    return source_id


def add_source(
    url: str | None = None,
    label: str | None = None,
    connectors_path: str = DEFAULT_CONNECTORS,
    search_path: str = DEFAULT_SEARCH,
    provider: str = "auto",
    token: str | None = None,
    tenant: str | None = None,
    datacenter: str | None = None,
    site: str | None = None,
    country: str = "com",
) -> SourceView:
    if provider == "scrape":
        preview = preview_source(url, label=label, provider="scrape")
        if not preview.ok:
            raise SourceError(preview.error or "Could not validate this source.")
        config = (
            load_connectors_config(connectors_path)
            if resolve_tenant_path(connectors_path).exists()
            else ConnectorsConfig()
        )
        scrape_spec = spec_for("scrape")
        assert scrape_spec is not None
        new_id = _append_unit(
            config, scrape_spec, target=None, url=preview.url, label=label
        )
        _save(connectors_path, config)
        return _view(config, new_id)

    if (
        provider == "auto"
        and search_path == DEFAULT_SEARCH
        and token is None
        and tenant is None
        and datacenter is None
        and site is None
        and country == "com"
    ):
        # Preserve the original service call shape for CLI/internal callers and
        # their test doubles. API requests pass their tenant-specific search path.
        preview = preview_source(url, label=label)
    else:
        preview = preview_source(
            url,
            label=label,
            search_path=search_path,
            provider=provider,
            token=token,
            tenant=tenant,
            datacenter=datacenter,
            site=site,
            country=country,
        )
    if not preview.ok:
        raise SourceError(preview.error or "Could not validate this source.")

    url = preview.url

    config = load_connectors_config(connectors_path)
    target = detect_ats(url)
    if target is None:
        raise SourceError("Could not detect a known ATS behind this URL.")

    spec = spec_for(target.ats)
    if spec is None or spec.new_unit is None or not spec.admits(target):
        spec = spec_for("companies")
        assert spec is not None

    new_id = _append_unit(config, spec, target=target, url=url, label=label)
    _save(connectors_path, config)
    return _view(config, new_id)


def set_source_enabled(
    source_id: str,
    enabled: bool,
    connectors_path: str = DEFAULT_CONNECTORS,
) -> SourceView:
    return patch_source(source_id, enabled=enabled, connectors_path=connectors_path)


def set_source_limit(
    source_id: str,
    limit: int | None,
    connectors_path: str = DEFAULT_CONNECTORS,
) -> SourceView:
    return patch_source(source_id, limit=limit, connectors_path=connectors_path)


def patch_source(
    source_id: str,
    *,
    enabled: bool | object = _UNSET,
    limit: int | None | object = _UNSET,
    connectors_path: str = DEFAULT_CONNECTORS,
) -> SourceView:
    """Apply all requested source changes to one config snapshot and save once."""
    if enabled is _UNSET and limit is _UNSET:
        raise SourceError("Provide enabled and/or limit.")
    if enabled is not _UNSET and not isinstance(enabled, bool):
        raise SourceError("enabled must be true or false.")
    if limit is not _UNSET and (
        isinstance(limit, bool)
        or (limit is not None and (not isinstance(limit, int) or limit < 1))
    ):
        raise SourceError("limit must be a positive integer or null.")

    config = load_connectors_config(connectors_path)
    found = True
    if enabled is not _UNSET:
        found = _apply_enabled(config, source_id, cast(bool, enabled))
    if limit is not _UNSET:
        found = _apply_limit(config, source_id, cast(int | None, limit)) and found
    if not found:
        raise SourceError(f"Unknown source '{source_id}'")
    _save(connectors_path, config)
    return _view(config, source_id)


def remove_source(source_id: str, connectors_path: str = DEFAULT_CONNECTORS) -> None:
    config = load_connectors_config(connectors_path)
    if not _remove(config, source_id):
        raise SourceError(f"Unknown source '{source_id}'")
    _save(connectors_path, config)


def _apply_enabled(config: ConnectorsConfig, source_id: str, enabled: bool) -> bool:
    found = find_unit(config, source_id)
    if found is None:
        return False
    spec, payload = found
    section = spec.section(config)
    if payload is None:
        section.enabled = enabled
        return True
    if enabled:
        section.enabled = True
    payload.enabled = enabled
    return True


def _apply_limit(config: ConnectorsConfig, source_id: str, limit: int | None) -> bool:
    found = find_unit(config, source_id)
    if found is None:
        return False
    spec, payload = found
    target = payload if payload is not None else spec.section(config)
    target.limit = limit
    return True


def _remove(config: ConnectorsConfig, source_id: str) -> bool:
    found = find_unit(config, source_id)
    if found is None:
        return False
    spec, payload = found
    if payload is None or spec.unit_items is None:
        return False
    spec.unit_items(config).remove(payload)
    return True
