# Discovery Scout ATS Resolution Accuracy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Discovery Scout find the correct durable ATS board for each proposed company, prove company ownership before marking it verified, and require an explicit audited override for unverified sources.

**Architecture:** Add a first-party provenance resolver beneath the Scout agent: a registry-backed supported-board catalog, bounded first-party crawler, provider-identity-aware ATS inspector, and deterministic ownership verifier. The agent spends a bounded search allowance finding official careers pages and targeted ATS candidates, while Python owns canonical URLs and verification state; the existing session, API, and proposal rail expose evidence, correction, and exact-URL manual confirmation.

**Tech Stack:** Python 3.13, Pydantic 2, FastAPI, httpx, BeautifulSoup 4, tldextract with its bundled suffix snapshot, Agno search tools, pytest, React 19, TypeScript, TanStack Query, Base UI, Vitest, Testing Library, OpenAPI TypeScript.

## Global Constraints

- The authoritative design is `docs/superpowers/specs/2026-08-14-discovery-scout-ats-resolution-design.md`.
- A reachable or populated board is never sufficient for `verified`; ownership needs a first-party provenance chain or provider-owned company metadata.
- Search results, token similarity, job-description text, and model confidence are candidate evidence only.
- Search failure can only lower confidence. It must never turn a guessed URL into `validated`.
- The default Scout allowance is five web-search calls per turn. The prompt, Anthropic native `max_uses`, fallback wrapper, and overall tool-call limit must agree with that policy where each provider permits enforcement.
- The resolver limits are five first-party pages, five ATS candidates, five redirects per request, 1 MiB per page, 15 seconds per request, 45 seconds per company, and four concurrent company resolutions.
- Agent tools remain read-only. Only existing deterministic services may mutate sessions or `connectors.yaml`, and only after an explicit user action.
- `CompanySourceResolution.status` projects to the existing proposal contract as `verified -> validated`, `unverified -> unverified`, `conflict -> conflict`, and `failed -> failed`.
- Ordinary approval accepts `validated` sources only. An `unverified` source requires the exact warned manual-confirmation path; `conflict`, `failed`, `avoid`, and `duplicate` never permit override.
- A generic unverified page may become a scrape target only after manual confirmation and only when the local browser is available.
- All remote input stays behind `security/outbound.py`; tests use injected fetchers and captured fixtures, never live network.
- Existing session files must load without migration. Every newly persisted field needs a backward-compatible default.
- Run Python tests through `.venv\Scripts\python.exe -m pytest` on Windows. Do not use the `pytest` console entrypoint.
- Keep task formatting/lint scoped to changed files. Run the full backend/web/lint/build suite only in the final verification task.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `src/resume_agent/discovery/source_resolution/catalog.py` | Supported ATS family metadata, canonical board URLs, and generated search guidance |
| `src/resume_agent/discovery/source_resolution/models.py` | Resolution, evidence, crawl, and reason-code value models |
| `src/resume_agent/discovery/source_resolution/identity.py` | Registrable-domain and company-name identity rules |
| `src/resume_agent/discovery/source_resolution/crawler.py` | Bounded first-party navigation and ATS candidate extraction |
| `src/resume_agent/discovery/source_resolution/resolver.py` | Candidate inspection, ownership verdict, and best-result selection |
| `src/resume_agent/discovery/source_resolution/search.py` | Five-use fallback search budget and streamed search-coverage tracking |
| `src/resume_agent/discovery/source_resolution/__init__.py` | Stable public imports for the resolver package |
| `src/resume_agent/discovery/connectors/base.py` | Provider-vs-token company provenance on fetched jobs |
| `src/resume_agent/discovery/connectors/detect.py` | Pure host detection plus all-target extraction from first-party HTML |
| `src/resume_agent/discovery/connectors/registry.py` | Attaches discovery metadata to the existing canonical connector registrations |
| `src/resume_agent/services/sources.py` | Canonical source roots and provider-company identities in `SourcePreview` |
| `src/resume_agent/discovery/scout.py` | Identity-aware read-only resolver tool and generated ATS search instructions |
| `src/resume_agent/discovery/scout_store.py` | Durable resolution evidence and manual-confirmation audit fields |
| `src/resume_agent/services/scout.py` | Resolver orchestration, deterministic post-processing, correction, and approval policy |
| `src/resume_agent/api/schemas/scout.py` | Resolve/approve request bodies and evidence-rich Scout responses |
| `src/resume_agent/api/routers/scout.py` | Source re-resolution route and optional manual approval body |
| `contracts/openapi.json` | Regenerated published API contract |
| `contracts/ts/api.ts` | Regenerated TypeScript API types |
| `web/src/lib/api/schema.ts` | SPA copy of the regenerated API types |
| `web/src/features/scout/use-scout.ts` | Resolve and manually-confirm mutations |
| `web/src/features/scout/proposals.ts` | Single source of truth for normal and manual eligibility |
| `web/src/features/scout/SourceVerificationActions.tsx` | Replacement-URL editor and warned exact-URL override dialog |
| `web/src/features/scout/ProposalCard.tsx` | Evidence/status presentation and source-verification actions |
| `web/src/features/scout/ProposalRail.tsx` | Batch-add exclusion of every unverified source |
| `evals/scout_source_cases.json` | Timestamped live Intuitive and Tempus expectations |
| `evals/scout_source_eval.py` | Live evaluation case/result types and resolver runner |
| `evals/run_scout_source_eval.py` | Opt-in, read-only command-line report |

---

### Task 1: Establish the supported-board catalog and canonical URL seam

**Files:**
- Create: `src/resume_agent/discovery/source_resolution/__init__.py`
- Create: `src/resume_agent/discovery/source_resolution/catalog.py`
- Modify: `src/resume_agent/discovery/connectors/detect.py:10-79,213-229`
- Modify: `src/resume_agent/discovery/connectors/registry.py:58-80,94-230`
- Modify: `src/resume_agent/services/sources.py:57-68,206-303`
- Create: `tests/test_source_resolution_catalog.py`
- Test: `tests/test_connector_detect.py`
- Test: `tests/test_services_sources.py:407-469`

**Interfaces:**
- Consumes: existing `AtsTarget`, `identify_host(url)`, `ConnectorSpec`, and source URL construction rules.
- Produces: `BoardFamily`, `BOARD_FAMILIES`, `board_family(kind)`, `canonical_target_url(target)`, `discoverable_board_families()`, `targeted_ats_query_templates()`, `render_supported_board_guidance(max_search_uses)`, and `targets_from_html(raw_html)`.

- [ ] **Step 1: Write failing catalog synchronization and canonicalization tests**

```python
# tests/test_source_resolution_catalog.py
from resume_agent.discovery.connectors.detect import identify_host
from resume_agent.discovery.connectors.registry import discoverable_board_families
from resume_agent.discovery.source_resolution.catalog import (
    BOARD_FAMILIES,
    canonical_target_url,
    render_supported_board_guidance,
    targeted_ats_query_templates,
)


EXPECTED = {
    "greenhouse", "lever", "ashby", "workday", "smartrecruiters",
    "workable", "recruitee", "personio", "breezy", "jazzhr", "bamboohr",
}


def test_every_supported_ats_is_registered_detectable_and_searchable():
    assert {family.kind for family in BOARD_FAMILIES} == EXPECTED
    assert {family.kind for family in discoverable_board_families()} == EXPECTED
    for family in BOARD_FAMILIES:
        target = identify_host(family.sample_url)
        assert target is not None and target.ats == family.kind
        assert canonical_target_url(target)


def test_generated_guidance_names_every_host_and_the_five_use_budget():
    guidance = render_supported_board_guidance(max_search_uses=5)
    assert "five web searches" in guidance
    for family in BOARD_FAMILIES:
        for host in family.search_hosts:
            assert host in guidance


def test_three_targeted_queries_cover_every_supported_host_exactly_once():
    templates = targeted_ats_query_templates()
    assert len(templates) == 3
    expected = sorted(host for family in BOARD_FAMILIES for host in family.search_hosts)
    actual = sorted(
        host.removeprefix("site:")
        for template in templates
        for host in template.split()
        if host.startswith("site:")
    )
    assert actual == expected


def test_smartrecruiters_canonical_root_is_the_public_careers_board():
    target = identify_host(
        "https://jobs.smartrecruiters.com/Intuitive/744000122414781-recruiter"
    )
    assert target is not None
    assert canonical_target_url(target) == "https://careers.smartrecruiters.com/Intuitive"
```

Add one parameterized detector test that embeds one sample URL from each `BoardFamily` inside script text and asserts `targets_from_html()` returns all eleven kinds, not only the first marker.

- [ ] **Step 2: Run the new tests and verify the missing catalog fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_source_resolution_catalog.py tests/test_connector_detect.py -q`

Expected: FAIL during collection because `source_resolution.catalog`, `discoverable_board_families`, and `targets_from_html` do not exist.

- [ ] **Step 3: Add the catalog with all supported families and canonical templates**

```python
# src/resume_agent/discovery/source_resolution/catalog.py
from dataclasses import dataclass
from html import unescape

from resume_agent.discovery.connectors.detect import AtsTarget


@dataclass(frozen=True)
class BoardFamily:
    kind: str
    label: str
    search_hosts: tuple[str, ...]
    sample_url: str
    canonical_template: str | None
    search_group: int


BOARD_FAMILIES = (
    BoardFamily("greenhouse", "Greenhouse", ("job-boards.greenhouse.io", "boards.greenhouse.io"), "https://job-boards.greenhouse.io/acme", "https://job-boards.greenhouse.io/{token}", 1),
    BoardFamily("lever", "Lever", ("jobs.lever.co",), "https://jobs.lever.co/acme", "https://jobs.lever.co/{token}", 1),
    BoardFamily("ashby", "Ashby", ("jobs.ashbyhq.com",), "https://jobs.ashbyhq.com/acme", "https://jobs.ashbyhq.com/{token}", 1),
    BoardFamily("workday", "Workday", ("myworkdayjobs.com",), "https://acme.wd5.myworkdayjobs.com/Acme_Careers", None, 1),
    BoardFamily("smartrecruiters", "SmartRecruiters", ("careers.smartrecruiters.com", "jobs.smartrecruiters.com"), "https://careers.smartrecruiters.com/acme", "https://careers.smartrecruiters.com/{token}", 2),
    BoardFamily("workable", "Workable", ("apply.workable.com", "workable.com"), "https://apply.workable.com/acme", "https://apply.workable.com/{token}", 2),
    BoardFamily("recruitee", "Recruitee", ("recruitee.com",), "https://acme.recruitee.com", "https://{token}.recruitee.com", 2),
    BoardFamily("personio", "Personio", ("jobs.personio.com", "jobs.personio.de"), "https://acme.jobs.personio.com", "https://{token}.jobs.personio.{country}", 2),
    BoardFamily("breezy", "Breezy", ("breezy.hr",), "https://acme.breezy.hr", "https://{token}.breezy.hr", 3),
    BoardFamily("jazzhr", "JazzHR", ("applytojob.com",), "https://acme.applytojob.com", "https://{token}.applytojob.com", 3),
    BoardFamily("bamboohr", "BambooHR", ("bamboohr.com",), "https://acme.bamboohr.com/careers", "https://{token}.bamboohr.com/careers", 3),
)

_BY_KIND = {family.kind: family for family in BOARD_FAMILIES}


def board_family(kind: str) -> BoardFamily | None:
    return _BY_KIND.get(kind)


def canonical_target_url(target: AtsTarget) -> str | None:
    if target.ats == "workday":
        if not (target.tenant and target.datacenter and target.site):
            return None
        return f"https://{target.tenant}.{target.datacenter}.myworkdayjobs.com/{target.site}"
    family = board_family(target.ats)
    if family is None or family.canonical_template is None or not target.token:
        return None
    return family.canonical_template.format(token=target.token, country=target.country)


def targeted_ats_query_templates() -> tuple[str, ...]:
    groups: dict[int, list[str]] = {}
    for family in BOARD_FAMILIES:
        groups.setdefault(family.search_group, []).extend(family.search_hosts)
    return tuple(
        '"{company}" ( ' + " OR ".join(f"site:{host}" for host in groups[group]) + " ) careers jobs"
        for group in sorted(groups)
    )


def render_supported_board_guidance(max_search_uses: int) -> str:
    rows = [
        f"- {family.label}: " + ", ".join(family.search_hosts)
        for family in BOARD_FAMILIES
    ]
    return "\n".join([
        f"Use at most {max_search_uses} web searches (five web searches by default).",
        'First search: "{company}" official careers jobs. Prefer the corporate careers domain.',
        "If unresolved, run these three generated ATS-host queries in order; stop immediately after ownership verifies:",
        *[f"- {query}" for query in targeted_ats_query_templates()],
        "Supported families and hosts:",
        *rows,
    ])
```

Export only the stable catalog functions from `source_resolution/__init__.py`.

- [ ] **Step 4: Make detector HTML extraction return every supported target**

Expose `targets_from_html(raw_html: str) -> list[AtsTarget]`. Preserve the current explicit Greenhouse/Ashby/Workday markers, then scan de-escaped absolute HTTP(S) URLs from raw script and markup text, pass each through `identify_host`, and deduplicate by the complete `AtsTarget` value. Make `_target_from_html()` return the first item from `targets_from_html()` so existing callers retain behavior.

```python
def targets_from_html(raw_html: str) -> list[AtsTarget]:
    html = unescape(raw_html).replace("\\/", "/")
    found: list[AtsTarget] = []
    for ats, pattern in _L2_MARKERS:
        if match := pattern.search(html):
            found.append(AtsTarget(ats, match.group(1)))
    for match in _WORKDAY_URL.finditer(html):
        if target := _workday_target(match.group("host").lower(), match.group("path") or ""):
            found.append(target)
    for raw_url in re.findall(r"https?://[^\"'<>\\s]+", html, re.IGNORECASE):
        if target := identify_host(raw_url.rstrip(").,;")):
            found.append(target)
    return list(dict.fromkeys(found))
```

- [ ] **Step 5: Attach catalog metadata to connector registrations and reuse canonical URLs**

Add `discovery: BoardFamily | None = None` to `ConnectorSpec`. Set it for Greenhouse, Lever, Ashby, and each native URL spec with a matching catalog family; leave Google, Tesla, companies, scrape, and aggregators as `None`. Add:

```python
def discoverable_board_families() -> tuple[BoardFamily, ...]:
    return tuple(
        spec.discovery
        for spec in CONNECTOR_SPECS
        if spec.discovery is not None
    )
```

Update `services.sources._connection_url()` and `board_root_url()` to use `canonical_target_url()` rather than the private `_TOKEN_URLS` table. Keep the explicit Workday field validation. Update the SmartRecruiters expectation in `tests/test_services_sources.py` to `https://careers.smartrecruiters.com/Acme`.

- [ ] **Step 6: Run focused catalog, detector, registry, and source tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_source_resolution_catalog.py tests/test_connector_detect.py tests/test_connectors_registry.py tests/test_services_sources.py -q`

Expected: PASS, including all eleven catalog entries and the SmartRecruiters public careers root.

- [ ] **Step 7: Commit the catalog seam**

```bash
git add src/resume_agent/discovery/source_resolution src/resume_agent/discovery/connectors/detect.py src/resume_agent/discovery/connectors/registry.py src/resume_agent/services/sources.py tests/test_source_resolution_catalog.py tests/test_connector_detect.py tests/test_services_sources.py
git commit -m "feat: centralize supported ATS discovery metadata"
```

---

### Task 2: Define resolution evidence and company identity rules

**Files:**
- Modify: `pyproject.toml:14-31`
- Modify: `uv.lock`
- Create: `src/resume_agent/discovery/source_resolution/models.py`
- Create: `src/resume_agent/discovery/source_resolution/identity.py`
- Modify: `src/resume_agent/discovery/source_resolution/__init__.py`
- Create: `tests/test_source_resolution_identity.py`

**Interfaces:**
- Consumes: untrusted company names, page URLs, HTML metadata, and the bundled Public Suffix List snapshot.
- Produces: `ResolutionStatus`, `ResolutionReason`, `EvidenceKind`, `SourceEvidence`, `CrawlCandidate`, `CrawlReport`, `CompanySourceResolution`, `normalize_company_name()`, `company_names_match()`, `registrable_domain()`, `same_registrable_domain()`, `company_claims_from_html()`, and `page_matches_company()`.

- [ ] **Step 1: Write failing value-model and identity tests**

```python
# tests/test_source_resolution_identity.py
from resume_agent.discovery.source_resolution.identity import (
    company_claims_from_html,
    company_names_match,
    registrable_domain,
)
from resume_agent.discovery.source_resolution.models import CompanySourceResolution


def test_brand_aliases_match_without_collapsing_similarly_named_companies():
    assert company_names_match("Intuitive Surgical", "Intuitive")
    assert company_names_match("Tempus AI, Inc.", "Tempus AI")
    assert not company_names_match("Intuitive Surgical", "Intuitive Machines")
    assert not company_names_match("Acme Healthcare", "Acme Manufacturing")


def test_registrable_domain_uses_the_bundled_suffix_snapshot():
    assert registrable_domain("https://careers.acme.co.uk/jobs") == "acme.co.uk"


def test_json_ld_and_open_graph_names_are_company_claims():
    html = '''<html><head><meta property="og:site_name" content="Intuitive">
    <script type="application/ld+json">{"@type":"Organization","name":"Intuitive Surgical","alternateName":"Intuitive"}</script></head></html>'''
    assert company_claims_from_html(html) == ("Intuitive", "Intuitive Surgical")


def test_resolution_defaults_are_safe_for_legacy_callers():
    result = CompanySourceResolution(company="Acme", requested_url="https://acme.test")
    assert result.status == "failed"
    assert result.evidence == []
    assert result.searched_families == []
```

- [ ] **Step 2: Run the tests and verify the models are absent**

Run: `.venv\Scripts\python.exe -m pytest tests/test_source_resolution_identity.py -q`

Expected: FAIL during collection because `models.py` and `identity.py` do not exist.

- [ ] **Step 3: Add the offline registrable-domain dependency**

Add `tldextract>=5.3.0` to runtime dependencies and run `uv lock`. Instantiate it with `suffix_list_urls=()` so tests and production never download a suffix list at runtime.

```python
import tldextract

_TLD = tldextract.TLDExtract(suffix_list_urls=())


def registrable_domain(url: str) -> str:
    host = (urlsplit(url).hostname or "").casefold().rstrip(".")
    parsed = _TLD(host)
    return ".".join(part for part in (parsed.domain, parsed.suffix) if part)
```

- [ ] **Step 4: Implement closed resolution and evidence models**

```python
# src/resume_agent/discovery/source_resolution/models.py
from typing import Literal
from pydantic import Field
from resume_agent.models.base import ExtensibleModel

ResolutionStatus = Literal["verified", "unverified", "conflict", "failed"]
ResolutionReason = Literal[
    "VERIFIED_FIRST_PARTY", "VERIFIED_PROVIDER_METADATA",
    "SEARCH_RATE_LIMITED", "SEARCH_BUDGET_EXHAUSTED",
    "OFFICIAL_SITE_UNREACHABLE", "ATS_NOT_FOUND",
    "OWNERSHIP_NOT_PROVEN", "ATS_CONFLICT", "RESOLUTION_TIMEOUT", "UNSAFE_URL",
]
EvidenceKind = Literal[
    "search_result", "first_party_identity", "first_party_link",
    "first_party_redirect", "first_party_embed", "provider_company", "provider_conflict",
]


class SourceEvidence(ExtensibleModel):
    kind: EvidenceKind
    source_url: str
    target_url: str = ""
    summary: str = ""


class CrawlCandidate(ExtensibleModel):
    url: str
    strong_first_party: bool = False
    evidence: list[SourceEvidence] = Field(default_factory=list)


class CrawlReport(ExtensibleModel):
    requested_url: str
    final_first_party_url: str = ""
    first_party_verified: bool = False
    candidates: list[CrawlCandidate] = Field(default_factory=list)
    evidence: list[SourceEvidence] = Field(default_factory=list)
    error_code: ResolutionReason | None = None


class CompanySourceResolution(ExtensibleModel):
    company: str
    requested_url: str
    canonical_board_url: str = ""
    ats: str | None = None
    token: str | None = None
    role_count: int | None = None
    status: ResolutionStatus = "failed"
    reason_code: ResolutionReason = "ATS_NOT_FOUND"
    evidence: list[SourceEvidence] = Field(default_factory=list)
    searched_families: list[str] = Field(default_factory=list)
    unsearched_families: list[str] = Field(default_factory=list)
```

- [ ] **Step 5: Implement conservative company-name and page-claim matching**

Normalize Unicode, casefold, replace punctuation with spaces, and remove only explicit legal suffixes (`inc`, `incorporated`, `corp`, `corporation`, `llc`, `ltd`, `limited`, `plc`, `gmbh`, `ag`, `co`, `company`). Match exact normalized tokens, or allow the shorter token sequence to be a subset only when all shorter tokens are shared and their combined length is at least five. This permits `Intuitive` versus `Intuitive Surgical` but rejects `Acme Healthcare` versus `Acme Manufacturing` because `acme` is only four characters.

Parse `<title>`, `og:site_name`, `application-name`, and JSON-LD `Organization.name`/`alternateName`; return deterministic sorted unique claims. `page_matches_company(company, url, html)` succeeds only when a claim or the registrable domain's brand label matches under the same conservative rule.

- [ ] **Step 6: Run focused tests and static checks**

Run: `.venv\Scripts\python.exe -m pytest tests/test_source_resolution_identity.py -q`

Run: `uv run ruff check src/resume_agent/discovery/source_resolution tests/test_source_resolution_identity.py`

Expected: both commands PASS without network access.

- [ ] **Step 7: Commit the identity boundary**

```bash
git add pyproject.toml uv.lock src/resume_agent/discovery/source_resolution tests/test_source_resolution_identity.py
git commit -m "feat: define Scout source ownership evidence"
```

---

### Task 3: Crawl first-party careers pages within explicit bounds

**Files:**
- Create: `src/resume_agent/discovery/source_resolution/crawler.py`
- Modify: `src/resume_agent/security/outbound.py:13-22,81-160`
- Modify: `src/resume_agent/discovery/source_resolution/__init__.py`
- Create: `tests/fixtures/scout_resolution/intuitive-careers.html`
- Create: `tests/fixtures/scout_resolution/tempus-careers.html`
- Create: `tests/fixtures/scout_resolution/multi-provider-embeds.html`
- Create: `tests/test_source_resolution_crawler.py`
- Create: `tests/test_security_outbound.py`

**Interfaces:**
- Consumes: `fetch_public_text()`, `targets_from_html()`, catalog canonicalization, identity helpers, and injected fixture fetchers.
- Produces: `PublicTextResponse.redirect_chain` and `FirstPartyCrawler(fetcher).crawl(company, candidate_url) -> CrawlReport`.

- [ ] **Step 1: Write failing redirect-chain, Intuitive, Tempus, and bound tests**

```python
# tests/test_source_resolution_crawler.py
from resume_agent.discovery.source_resolution.crawler import FirstPartyCrawler
from resume_agent.security.outbound import PublicTextResponse


def response(url: str, html: str, *redirects: str) -> PublicTextResponse:
    return PublicTextResponse(
        final_url=url,
        text=html,
        content_type="text/html",
        redirect_chain=redirects,
    )


def test_intuitive_first_party_link_is_strong(load_fixture):
    pages = {
        "https://careers.intuitive.com/en/": response(
            "https://careers.intuitive.com/en/",
            load_fixture("scout_resolution/intuitive-careers.html"),
        )
    }
    report = FirstPartyCrawler(fetcher=pages.__getitem__).crawl(
        "Intuitive Surgical", "https://careers.intuitive.com/en/"
    )
    assert report.first_party_verified
    assert report.candidates[0].url == "https://careers.smartrecruiters.com/intuitive"
    assert report.candidates[0].strong_first_party


def test_tempus_workday_posting_is_reduced_to_the_board_root(load_fixture):
    pages = {
        "https://www.tempus.com/careers/": response(
            "https://www.tempus.com/careers/",
            load_fixture("scout_resolution/tempus-careers.html"),
        )
    }
    report = FirstPartyCrawler(fetcher=pages.__getitem__).crawl(
        "Tempus", "https://www.tempus.com/careers/"
    )
    assert report.candidates[0].url == "https://tempus.wd5.myworkdayjobs.com/Tempus_Careers"


def test_crawler_never_fetches_more_than_five_first_party_pages():
    fetched: list[str] = []
    def fetch(url: str) -> PublicTextResponse:
        fetched.append(url)
        links = "".join(f'<a href="https://acme.com/careers/{i}">Jobs</a>' for i in range(10))
        return response(url, f"<title>Acme Careers</title>{links}")
    FirstPartyCrawler(fetcher=fetch).crawl("Acme", "https://acme.com/careers")
    assert len(fetched) == 5
```

Add an outbound test asserting a two-hop redirect returns the complete normalized chain and still revalidates each destination.

- [ ] **Step 2: Run the crawler and outbound tests to verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests/test_source_resolution_crawler.py tests/test_security_outbound.py -q`

Expected: FAIL because `FirstPartyCrawler` and `redirect_chain` are absent.

- [ ] **Step 3: Preserve redirect provenance in the outbound response**

Add `redirect_chain: tuple[str, ...] = ()` to `PublicTextResponse`. In `fetch_public_text()`, initialize the chain with the requested normalized URL, append every validated redirect destination, and return the chain with the final response. The default keeps existing test constructors backward-compatible.

- [ ] **Step 4: Implement bounded first-party crawling and candidate extraction**

```python
# src/resume_agent/discovery/source_resolution/crawler.py
MAX_FIRST_PARTY_PAGES = 5
MAX_ATS_CANDIDATES = 5
MAX_PAGE_BYTES = 1_048_576
REQUEST_TIMEOUT_SECONDS = 15.0
RESOLUTION_DEADLINE_SECONDS = 45.0
CAREER_WORDS = ("career", "job", "join", "position", "opportunit", "vacanc", "work-with")


class FirstPartyCrawler:
    def __init__(self, fetcher=None, clock=time.monotonic):
        self._fetch = fetcher or self._fetch_page
        self._clock = clock

    @staticmethod
    def _fetch_page(url: str) -> PublicTextResponse:
        return fetch_public_text(
            url,
            timeout=REQUEST_TIMEOUT_SECONDS,
            max_bytes=MAX_PAGE_BYTES,
        )

    def crawl(self, company: str, candidate_url: str) -> CrawlReport:
        validate_public_url(candidate_url)
        direct = identify_host(candidate_url)
        if direct is not None:
            canonical = canonical_target_url(direct) or board_root_url(candidate_url)
            return CrawlReport(
                requested_url=candidate_url,
                candidates=[CrawlCandidate(
                    url=canonical,
                    evidence=[SourceEvidence(
                        kind="search_result",
                        source_url=candidate_url,
                        target_url=canonical,
                        summary="Direct ATS candidate from web research.",
                    )],
                )],
            )
        return self._crawl_first_party(company, candidate_url)
```

`_crawl_first_party()` must:

- check the overall deadline before every fetch;
- visit at most five unique URLs;
- establish the first-party registrable domain from the verified starting page;
- queue only same-domain links whose URL or visible text contains a careers word;
- inspect `a[href]`, `iframe[src]`, `script[src]`, and `form[action]` attributes;
- call `targets_from_html()` on raw HTML to catch embedded/script URLs;
- turn every recognized posting into `canonical_target_url(target)`;
- mark an ATS candidate strong only when it came from an identity-matching first-party page by link, redirect, or embed;
- stop after five unique canonical ATS candidates;
- return `UNSAFE_URL`, `OFFICIAL_SITE_UNREACHABLE`, or `RESOLUTION_TIMEOUT` as data rather than raising.

Do not fetch the ATS candidate inside the crawler; candidate inspection belongs to the resolver.

- [ ] **Step 5: Add realistic captured HTML fixtures**

`intuitive-careers.html` must identify `Intuitive` in title/JSON-LD and link to `https://careers.smartrecruiters.com/intuitive`. `tempus-careers.html` must identify `Tempus` and link to a Workday posting under `tempus.wd5.myworkdayjobs.com/en-US/Tempus_Careers/job/...`. `multi-provider-embeds.html` must include raw escaped URLs for all catalog hosts so extraction coverage is independent of browser rendering.

- [ ] **Step 6: Run crawler, detector, and outbound regression tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_source_resolution_crawler.py tests/test_security_outbound.py tests/test_connector_detect.py tests/url_ingest/test_fetch.py -q`

Expected: PASS with no live DNS or HTTP calls.

- [ ] **Step 7: Commit first-party crawling**

```bash
git add src/resume_agent/security/outbound.py src/resume_agent/discovery/source_resolution tests/fixtures/scout_resolution tests/test_source_resolution_crawler.py tests/test_security_outbound.py
git commit -m "feat: crawl first-party careers provenance"
```

---

### Task 4: Inspect ATS candidates with provider-owned company metadata

**Files:**
- Modify: `src/resume_agent/discovery/connectors/base.py:31-42`
- Modify: `src/resume_agent/discovery/connectors/greenhouse.py:34-98`
- Modify: `src/resume_agent/discovery/connectors/smartrecruiters.py:52-70`
- Modify: `src/resume_agent/discovery/connectors/workday.py:192-246`
- Modify: `src/resume_agent/discovery/connectors/workable.py:31-55`
- Modify: `src/resume_agent/discovery/connectors/recruitee.py:24-43`
- Modify: `src/resume_agent/discovery/connectors/breezy.py:15-42`
- Modify: `src/resume_agent/discovery/connectors/jazzhr.py:19-58`
- Modify: `src/resume_agent/services/sources.py:75-84,376-409`
- Create: `src/resume_agent/discovery/source_resolution/resolver.py`
- Modify: `src/resume_agent/discovery/source_resolution/__init__.py`
- Create: `tests/test_connector_company_provenance.py`
- Create: `tests/test_source_resolution_resolver.py`
- Create: `tests/test_scout_resolution_golden.py`

**Interfaces:**
- Consumes: `FirstPartyCrawler`, `SourcePreview`, connector `RawJob` rows, company identity rules, and existing `preview_source()`.
- Produces: `RawJob.company_provenance`, `SourcePreview.observed_companies`, `resolution_cache_key(company, url)`, and `CompanySourceResolver.resolve(company, candidate_url) -> CompanySourceResolution`.

- [ ] **Step 1: Write failing connector provenance and resolver verdict tests**

```python
# tests/test_source_resolution_resolver.py
from resume_agent.discovery.source_resolution.models import CrawlCandidate, CrawlReport, SourceEvidence
from resume_agent.discovery.source_resolution.resolver import CompanySourceResolver
from resume_agent.services.sources import SourcePreview


def strong_report(company: str, url: str) -> CrawlReport:
    return CrawlReport(
        requested_url=url,
        first_party_verified=True,
        candidates=[CrawlCandidate(
            url=url,
            strong_first_party=True,
            evidence=[SourceEvidence(
                kind="first_party_link",
                source_url=f"https://{company.casefold()}.example/careers",
                target_url=url,
                summary="Official careers page links to this board.",
            )],
        )],
    )


def test_first_party_board_verifies_even_when_provider_name_is_unavailable():
    resolver = CompanySourceResolver(
        search_path="search.yaml",
        crawler=lambda company, url: strong_report(company, url),
        previewer=lambda url, **kwargs: SourcePreview(
            ok=True, url=url, kind="lever", token="acme", role_count=3
        ),
    )
    result = resolver.resolve("Acme", "https://jobs.lever.co/acme")
    assert result.status == "verified"
    assert result.reason_code == "VERIFIED_FIRST_PARTY"


def test_direct_populated_board_with_another_provider_company_is_conflict():
    resolver = CompanySourceResolver(
        search_path="search.yaml",
        previewer=lambda url, **kwargs: SourcePreview(
            ok=True,
            url=url,
            kind="workday",
            token="tempus",
            role_count=5,
            observed_companies=("Tempus AI",),
        ),
    )
    result = resolver.resolve("Intuitive Surgical", "https://tempus.wd5.myworkdayjobs.com/Tempus_Careers")
    assert result.status == "conflict"
    assert result.reason_code == "ATS_CONFLICT"


def test_direct_board_without_first_party_or_provider_identity_is_unverified():
    resolver = CompanySourceResolver(
        search_path="search.yaml",
        previewer=lambda url, **kwargs: SourcePreview(
            ok=True, url=url, kind="lever", token="tempus", role_count=2
        ),
    )
    assert resolver.resolve("Tempus", "https://jobs.lever.co/tempus").status == "unverified"
```

Add parameterized connector tests proving Greenhouse board-name API, SmartRecruiters `company.name`, Workday detail `companyName`, Workable top-level `name`, Recruitee `company_name`, Breezy `hiringOrganization.name`, and JazzHR `hiringOrganization.name` set `company_provenance="provider"`; token/configured fallbacks do not.

- [ ] **Step 2: Run the provenance and resolver tests to verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests/test_connector_company_provenance.py tests/test_source_resolution_resolver.py -q`

Expected: FAIL because provenance fields, observed companies, and the resolver do not exist.

- [ ] **Step 3: Add company provenance to connector rows and previews**

Add this backward-compatible field at the end of `RawJob`:

```python
company_provenance: Literal["provider", "configured", "token", "fixed", "unknown"] = "unknown"
```

Set `provider` only when the named remote field is actually present. Set token/configured fallbacks explicitly. Do not infer provider identity from the board slug. In `preview_source()`, collect stable unique names only from rows with `company_provenance == "provider"`:

```python
observed = tuple(dict.fromkeys(
    job.company.strip()
    for job in result.jobs
    if job.company_provenance == "provider" and job.company and job.company.strip()
))
```

Add `observed_companies: tuple[str, ...] = ()` to `SourcePreview`; it remains internal and is not directly copied from model output.

- [ ] **Step 4: Implement deterministic candidate selection and ownership verdicts**

```python
# src/resume_agent/discovery/source_resolution/resolver.py
def resolution_cache_key(company: str, url: str) -> tuple[str, str]:
    return normalize_company_name(company), board_root_url(url.strip())


class CompanySourceResolver:
    def __init__(self, search_path: str, *, crawler=None, previewer=preview_source):
        self.search_path = search_path
        self._crawler = crawler or FirstPartyCrawler().crawl
        self._preview = previewer

    def resolve(self, company: str, candidate_url: str) -> CompanySourceResolution:
        report = self._crawler(company, candidate_url)
        inspected = [self._inspect(company, candidate) for candidate in report.candidates[:5]]
        verified = next((row for row in inspected if row.status == "verified"), None)
        if verified is not None:
            return verified
        unverified = next((row for row in inspected if row.status == "unverified"), None)
        if unverified is not None:
            return unverified
        conflict = next((row for row in inspected if row.status == "conflict"), None)
        if conflict is not None:
            return conflict
        if report.first_party_verified:
            return CompanySourceResolution(
                company=company,
                requested_url=candidate_url,
                canonical_board_url=report.final_first_party_url or candidate_url,
                status="unverified",
                reason_code="ATS_NOT_FOUND",
                evidence=report.evidence,
            )
        return CompanySourceResolution(
            company=company,
            requested_url=candidate_url,
            status="failed",
            reason_code=report.error_code or "ATS_NOT_FOUND",
            evidence=report.evidence,
        )
```

`_inspect()` calls `preview_source(canonical_url, search_path=self.search_path, limit=5, browser=False)`. Evaluate provider-owned names before issuing the final verdict: a provider-name conflict yields `ATS_CONFLICT` even when a first-party page linked the candidate; a provider-name match yields `VERIFIED_PROVIDER_METADATA`; otherwise a successful strong first-party candidate yields `VERIFIED_FIRST_PARTY`; and a populated candidate with neither identity signal yields `OWNERSHIP_NOT_PROVEN`. Unreachable candidates remain failed and do not abort siblings. Add a regression proving a first-party link cannot suppress contradictory provider-owned identity.

- [ ] **Step 5: Add offline golden regressions for Intuitive and Tempus**

Use the Task 3 first-party fixtures plus injected previews:

```python
def test_intuitive_resolves_smartrecruiters_not_workday(resolver):
    result = resolver.resolve("Intuitive Surgical", "https://careers.intuitive.com/en/")
    assert result.status == "verified"
    assert result.ats == "smartrecruiters"
    assert result.canonical_board_url == "https://careers.smartrecruiters.com/intuitive"


def test_tempus_resolves_workday_not_lever(resolver):
    result = resolver.resolve("Tempus", "https://www.tempus.com/careers/")
    assert result.status == "verified"
    assert result.ats == "workday"
    assert result.canonical_board_url == "https://tempus.wd5.myworkdayjobs.com/Tempus_Careers"
```

Also assert that a live Lever `tempus` candidate without first-party/provider proof remains unverified.

Add a parameterized resolver test over every `BoardFamily.sample_url`. For each of the eleven supported families, inject a matching first-party provenance report and a successful preview, then assert the resolver returns that family, its exact `canonical_target_url()`, and `verified`. This is the offline proof that adding a connector to the catalog also exercises its detector, canonicalizer, and ownership-verdict path.

- [ ] **Step 6: Run connector, resolver, source-preview, and golden tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_connector_company_provenance.py tests/test_source_resolution_resolver.py tests/test_scout_resolution_golden.py tests/test_services_sources_preview.py tests/test_connector_greenhouse.py tests/test_connector_smartrecruiters.py tests/test_connector_workday.py tests/test_connector_workable.py tests/test_connector_recruitee.py tests/test_connector_breezy.py tests/test_connector_jazzhr.py -q`

Expected: PASS with zero false verified boards.

- [ ] **Step 7: Commit provider-aware resolution**

```bash
git add src/resume_agent/discovery/connectors/base.py src/resume_agent/discovery/connectors/greenhouse.py src/resume_agent/discovery/connectors/smartrecruiters.py src/resume_agent/discovery/connectors/workday.py src/resume_agent/discovery/connectors/workable.py src/resume_agent/discovery/connectors/recruitee.py src/resume_agent/discovery/connectors/breezy.py src/resume_agent/discovery/connectors/jazzhr.py src/resume_agent/discovery/source_resolution/resolver.py src/resume_agent/discovery/source_resolution/__init__.py src/resume_agent/services/sources.py tests/test_connector_company_provenance.py tests/test_source_resolution_resolver.py tests/test_scout_resolution_golden.py
git commit -m "feat: verify ATS ownership for Scout sources"
```

---

### Task 5: Persist resolution evidence and exact manual-confirmation audits

**Files:**
- Modify: `src/resume_agent/discovery/scout_store.py:22-65,190-209`
- Modify: `src/resume_agent/services/scout.py:67-75,469-533`
- Test: `tests/test_scout_store.py`
- Test: `tests/test_scout_enrichment_schemas.py`
- Test: `tests/test_scout_service.py`

**Interfaces:**
- Consumes: `CompanySourceResolution`, `SourceEvidence`, existing session JSON, and proposal status mutations.
- Produces: evidence-rich `SourcePayload`, `ManualSourceConfirmation`, `ScoutProposal.check="conflict"`, `replace_pending_source_resolution()`, and `set_proposal_status(..., confirmation=...)`.

- [ ] **Step 1: Write failing backward-compatibility, compare-and-swap, and audit tests**

```python
def test_legacy_source_payload_defaults_resolution_fields():
    payload = SourcePayload.model_validate({"company": "Acme", "url": "https://acme.test"})
    assert payload.resolution_status is None
    assert payload.evidence == []
    assert payload.searched_families == []


def test_replacement_requires_the_pending_exact_url(tmp_path):
    session = seed_source_session(tmp_path, url="https://old.example/jobs")
    with pytest.raises(ValueError, match="source URL changed"):
        replace_pending_source_resolution(
            tmp_path,
            session["session_id"],
            "p1",
            expected_url="https://stale.example/jobs",
            resolution=verified_resolution("https://new.example/jobs"),
        )


def test_added_override_persists_exact_confirmation(tmp_path):
    confirmation = ManualSourceConfirmation(
        company="Acme",
        url="https://jobs.lever.co/acme",
        ats="lever",
        resolution_reason="OWNERSHIP_NOT_PROVEN",
        confirmed_at="2026-08-14T12:00:00Z",
    )
    set_proposal_status(tmp_path, "s1", "p1", "added", confirmation=confirmation)
    row = load_session(tmp_path, "s1")["proposals"][0]
    assert row["manual_confirmation"]["url"] == "https://jobs.lever.co/acme"
```

- [ ] **Step 2: Run store and schema tests to verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests/test_scout_store.py tests/test_scout_enrichment_schemas.py -q`

Expected: FAIL because resolution and confirmation fields and replacement mutation are absent.

- [ ] **Step 3: Extend persisted models with safe defaults**

```python
class ManualSourceConfirmation(ExtensibleModel):
    company: str
    url: str
    ats: str | None = None
    resolution_reason: str
    confirmed_at: str


class SourcePayload(ExtensibleModel):
    company: str = ""
    url: str = ""
    ats: str | None = None
    token: str | None = None
    role_count: int | None = None
    error_code: str | None = None
    resolution_status: ResolutionStatus | None = None
    resolution_reason: str = ""
    evidence: list[SourceEvidence] = Field(default_factory=list)
    searched_families: list[str] = Field(default_factory=list)
    unsearched_families: list[str] = Field(default_factory=list)
```

Add `conflict` to the `ScoutProposal.check` literal and `manual_confirmation: ManualSourceConfirmation | None = None` to `ScoutProposal`. Existing stored sessions must validate unchanged.

- [ ] **Step 4: Add exact-URL resolution replacement and confirmation-aware status mutation**

`replace_pending_source_resolution()` must mutate under `SessionStore`, require pending/source/exact `expected_url`, replace the source only from `CompanySourceResolution`, project status to `check`, set a concise `check_error` for failed/conflict, clear `manual_confirmation`, and leave company identity unchanged.

Extend `set_proposal_status()` with `confirmation: ManualSourceConfirmation | None = None`; accept it only for `status="added"`, persist it on the same proposal mutation as status/resolved time, and reject a confirmation whose company or URL differs from the proposal.

- [ ] **Step 5: Project all new fields through `session_view()`**

Extend `_camel_source()` with `resolutionStatus`, `resolutionReason`, `evidence`, `searchedFamilies`, and `unsearchedFamilies`; extend `_camel_proposal()` with `manualConfirmation`. Add `conflict` to `_CHECK_RANK` after `avoid` and before `failed`.

- [ ] **Step 6: Run store, service-view, and legacy-session tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_scout_store.py tests/test_scout_enrichment_schemas.py tests/test_scout_service.py -q`

Expected: PASS, including loading sessions written before these fields existed.

- [ ] **Step 7: Commit durable resolution state**

```bash
git add src/resume_agent/discovery/scout_store.py src/resume_agent/services/scout.py tests/test_scout_store.py tests/test_scout_enrichment_schemas.py tests/test_scout_service.py
git commit -m "feat: persist Scout source verification evidence"
```

---

### Task 6: Give the Scout a budgeted identity-aware resolver tool

**Files:**
- Create: `src/resume_agent/discovery/source_resolution/search.py`
- Modify: `src/resume_agent/llm_runner.py:1406-1463`
- Modify: `src/resume_agent/discovery/scout.py:14-28,238-336`
- Modify: `src/resume_agent/services/scout.py:12-61,87-240,243-323`
- Create: `tests/test_source_resolution_search.py`
- Test: `tests/test_llm_runner_search_equipped.py`
- Test: `tests/test_scout.py`
- Test: `tests/test_scout_service.py`
- Test: `tests/test_prompt_registry.py`

**Interfaces:**
- Consumes: `CompanySourceResolver`, five-use policy, catalog guidance, Agno fallback web search, stream events, and resolution cache fields from Task 5.
- Produces: `SearchBudget`, `make_budgeted_web_search_tool()`, `SearchCoverageSink`, `make_resolve_company_source_tool()`, `build_scout_agent(resolve_tool, search_budget)`, and resolver-driven `_post_process()`.

- [ ] **Step 1: Write failing budget, tool-boundary, prompt, cache, and downgrade tests**

```python
def test_fallback_search_opens_the_circuit_after_rate_limit(monkeypatch):
    backend_calls = 0
    def backend(query: str, max_results: int = 5) -> str:
        nonlocal backend_calls
        backend_calls += 1
        raise RatelimitException("too many requests")
    budget = SearchBudget(max_uses=5)
    search = make_budgeted_web_search_tool(budget, backend=backend)
    first = json.loads(search("Intuitive careers"))
    second = json.loads(search("Tempus careers"))
    assert first["error_code"] == "SEARCH_RATE_LIMITED"
    assert second["error_code"] == "SEARCH_RATE_LIMITED"
    assert backend_calls == 1


def test_scout_tools_are_search_plus_company_resolver(monkeypatch):
    seen = capture_agent_tool_names(monkeypatch)
    scout.build_scout_agent(lambda company, url: "{}", SearchBudget())
    assert "resolve_company_source" in seen
    assert "check_source" not in seen


def test_prompt_lists_every_supported_ats_host():
    instructions = scout.scout_instructions()
    for family in BOARD_FAMILIES:
        assert all(host in instructions for host in family.search_hosts)


def test_post_process_never_validates_a_live_unowned_board(tmp_path):
    result = CompanySourceResolution(
        company="Tempus",
        requested_url="https://jobs.lever.co/tempus",
        canonical_board_url="https://jobs.lever.co/tempus",
        ats="lever",
        status="unverified",
        reason_code="OWNERSHIP_NOT_PROVEN",
    )
    proposals = service._post_process(
        Reporter(),
        [source_draft("Tempus", result.requested_url)],
        session={"proposals": []},
        connectors_path=str(tmp_path / "connectors.yaml"),
        search_path=str(tmp_path / "search.yaml"),
        resolve_source=lambda company, url: result,
    )
    assert proposals[0].check == "unverified"
```

Add a cache test proving `("Intuitive Surgical", posting_url)` and post-processing's canonical company/URL key invoke the resolver once, plus a rate-limit coverage test that changes unresolved `ATS_NOT_FOUND` into `SEARCH_RATE_LIMITED` without changing a verified sibling.

- [ ] **Step 2: Run focused tests and verify the old probe boundary fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_source_resolution_search.py tests/test_scout.py tests/test_scout_service.py tests/test_llm_runner_search_equipped.py tests/test_prompt_registry.py -q`

Expected: FAIL because the search budget, resolver tool, generated guidance, and new `_post_process` seam do not exist.

- [ ] **Step 3: Implement the fallback five-use budget and rate-limit circuit**

```python
# src/resume_agent/discovery/source_resolution/search.py
@dataclass
class SearchBudget:
    max_uses: int = 5
    used: int = 0
    rate_limited: bool = False
    queries: list[str] = field(default_factory=list)

    def reserve(self, query: str) -> str | None:
        if self.rate_limited:
            return "SEARCH_RATE_LIMITED"
        if self.used >= self.max_uses:
            return "SEARCH_BUDGET_EXHAUSTED"
        self.used += 1
        self.queries.append(query)
        return None


def make_budgeted_web_search_tool(budget: SearchBudget, *, backend=None):
    delegate = backend or DuckDuckGoTools(enable_news=False, fixed_max_results=5).web_search
    def web_search(query: str) -> str:
        if error := budget.reserve(query):
            return json.dumps({"ok": False, "error_code": error, "results": []})
        try:
            return delegate(query, 5)
        except RatelimitException:
            budget.rate_limited = True
            return json.dumps({"ok": False, "error_code": "SEARCH_RATE_LIMITED", "results": []})
        except TimeoutException:
            return json.dumps({"ok": False, "error_code": "SEARCH_BUDGET_EXHAUSTED", "results": []})
    return web_search
```

Name the returned function `web_search` and give it a concrete docstring so Agno publishes the expected tool schema. Do not expose the news tool.

- [ ] **Step 4: Permit a Scout-specific fallback search callable without changing other agents**

Add optional `tool_search: Any | None = None` to `build_search_equipped()`. Use it only in the `plan.strategy == "tool"` branch; when absent, preserve `DuckDuckGoTools()` exactly. Extend existing tests to prove all native strategies and default fallback output remain unchanged.

- [ ] **Step 5: Track streamed searches while forwarding every event unchanged**

`SearchCoverageSink` implements `StreamSink`, delegates `emit()`/`close()`, records `ToolStarted` queries by call id, identifies family hosts from the catalog, and observes `SEARCH_RATE_LIMITED`/rate-limit text in `ToolCompleted`. Its snapshot returns deterministic sorted `searched_families`, the catalog complement, and the strongest interruption reason. It must not swallow, reorder, or rewrite stream events.

- [ ] **Step 6: Replace `check_source` with `resolve_company_source` and generated guidance**

```python
def make_resolve_company_source_tool(
    search_path: str,
    *,
    cache: dict[tuple[str, str], CompanySourceResolution] | None = None,
    resolver: CompanySourceResolver | None = None,
):
    source_resolver = resolver or CompanySourceResolver(search_path)
    def resolve_company_source(company: str, candidate_url: str) -> str:
        key = resolution_cache_key(company, candidate_url)
        result = cache.get(key) if cache is not None else None
        if result is None:
            result = source_resolver.resolve(company, candidate_url)
            if cache is not None:
                cache[key] = result
        return result.model_dump_json()
    return resolve_company_source
```

Change static `_SCOUT_INSTRUCTIONS` into `scout_instructions()` so it appends `render_supported_board_guidance(5)`. Require official-careers search first, batched ATS-host fallback second, no guessed slugs, stop after verified ownership, and explicit unverified language after interrupted coverage. Keep the formatter prohibition on inventing URLs and verification state.

`build_scout_agent()` creates one `SearchBudget`, passes its fallback callable to `build_search_equipped(tool_search=...)`, exposes the returned search tool(s) plus `resolve_company_source`, and retains the existing overall `tool_call_limit=15`. Anthropic continues to enforce native `max_uses=5`; native tools that expose no per-tool cap are constrained by the prompt and overall limit.

- [ ] **Step 7: Drive post-processing exclusively from resolver results**

Replace the URL-only `SourcePreview` cache and fan-out with a company+URL `CompanySourceResolution` cache. For each fresh positive source, call the resolver in `asyncio.to_thread` through `gather_isolated`, with a shared `asyncio.Semaphore(4)` acquired by the per-item coroutine; map only the deterministic result into `SourcePayload`; merge the `SearchCoverageSink` snapshot; and project statuses through the Task 5 table. If coverage reports a rate limit or exhausted budget and the result is still unresolved, use that reason without modifying a verified result. Add a concurrency test whose injected resolver records active calls and proves the maximum is four.

Retain duplicate and avoid behavior, proposal caps, isolated failures, reporter checkpoints, and deterministic ranking.

- [ ] **Step 8: Run prompt, search, Scout, and service regressions**

Run: `.venv\Scripts\python.exe -m pytest tests/test_source_resolution_search.py tests/test_llm_runner_search_equipped.py tests/test_scout.py tests/test_scout_service.py tests/test_prompt_registry.py tests/test_scout_resolution_golden.py -q`

Expected: PASS; tool events remain ordered, resolver calls are cached, and no live populated board verifies without ownership evidence.

- [ ] **Step 9: Commit the agent search/resolution flow**

```bash
git add src/resume_agent/discovery/source_resolution/search.py src/resume_agent/llm_runner.py src/resume_agent/discovery/scout.py src/resume_agent/services/scout.py tests/test_source_resolution_search.py tests/test_llm_runner_search_equipped.py tests/test_scout.py tests/test_scout_service.py tests/test_prompt_registry.py
git commit -m "feat: make Scout ATS search ownership-aware"
```

### Task 7: Enforce verification at the service and API boundary

**Files:**
- Modify: `src/resume_agent/discovery/scout_store.py`
- Modify: `src/resume_agent/services/scout.py`
- Modify: `src/resume_agent/api/schemas/scout.py`
- Modify: `src/resume_agent/api/routers/scout.py`
- Test: `tests/test_scout_store.py`
- Test: `tests/test_scout_service.py`
- Test: `tests/api/test_scout_router.py`
- Create: `tests/api/test_schemas_scout.py`

- [ ] **Step 1: Write failing store compare-and-swap tests for replacing a pending URL**

Add tests covering all of these cases:

- a pending source proposal can replace its exact expected URL with a newly resolved payload;
- a stale `expected_url` is rejected without mutation;
- added, rejected, non-source, and missing proposals cannot be replaced;
- replacement clears an earlier manual-confirmation record and preserves the proposal id;
- conflict evidence is persisted but cannot be marked manually confirmed.

Use an explicit store entry point rather than a generic mutation callback. Its exact interface is `replace_pending_source_resolution(workspace_root: Path | str, session_id: str, proposal_id: str, *, expected_url: str, resolution: CompanySourceResolution) -> dict`.

Define `ScoutProposalChangedError(ValueError)` for the stale compare-and-swap case so the router can distinguish it from an invalid request. The store accepts a closed `CompanySourceResolution`, not caller-selected `SourcePayload` and `check` values.

- [ ] **Step 2: Write failing service tests for normal approval, override, and re-resolution**

Test the authorization matrix directly:

| Proposal state | Normal approval | `manual_confirmation=True` |
|---|---:|---:|
| verified source | allowed | allowed, but no audit override is recorded |
| unverified known ATS | rejected | allowed and audited |
| unverified generic URL with browser enabled | rejected | allowed and audited |
| unverified generic URL without browser | rejected | rejected |
| ownership conflict | rejected | rejected |
| failed source | rejected | rejected |
| eligible search-term proposal | allowed | allowed |

Also test `resolve_proposal_source()` with an injected resolver: it loads the pending snapshot, performs network-independent resolution outside the file lock, then compare-and-swaps only if the URL is still current. A verified replacement becomes normally addable; an unverified replacement remains blocked from normal approval.

- [ ] **Step 3: Add request and response schemas**

```python
class ScoutApproveIn(CamelModel):
    manual_confirmation: bool = False


class ScoutResolveSourceIn(CamelModel):
    url: AnyHttpUrl = Field(max_length=2048)


class ScoutEvidenceOut(CamelModel):
    kind: str
    source_url: str
    target_url: str = ""
    summary: str = ""


class ScoutManualConfirmationOut(CamelModel):
    company: str
    url: str
    ats: str | None = None
    resolution_reason: str
    confirmed_at: str
```

Extend `ScoutSourceOut` with Python fields `requested_url`, `canonical_board_url`, `resolution_status`, `resolution_reason`, `evidence`, `searched_families`, and `unsearched_families`; `CamelModel` publishes them as `requestedUrl`, `canonicalBoardUrl`, `resolutionStatus`, `resolutionReason`, `evidence`, `searchedFamilies`, and `unsearchedFamilies`. Extend the proposal output with `manual_confirmation`, and add `"conflict"` to the check enum. Preserve defaults so old ledger rows still deserialize.

- [ ] **Step 4: Implement the approval guard and server-created audit record**

Extend the existing service interface with `manual_confirmation: bool = False`, retaining its current `workspace_root`, ids, `config_store`, `connectors_path`, `search_path`, and `browser_enabled` parameters.

The server must derive `company`, exact current `url`, `ats`, and `resolution_reason` from the stored proposal; never accept audit content from the client. Add a source normally only when `check == "validated"`. For an unverified override, use the detected connector automatically, or `scrape` only when browser support is enabled. Reject conflict and failed states even with the flag. Persist `ManualSourceConfirmation` only after `add_source()` succeeds, in the same locked ledger mutation that changes the proposal to `added`; a failed source mutation must leave no confirmation record.

- [ ] **Step 5: Implement exact-URL re-resolution**

Add `resolve_proposal_source(workspace_root: Path | str, session_id: str, proposal_id: str, *, url: str, search_path: str, browser_enabled: bool, resolver: CompanySourceResolver | None = None) -> dict`.

Validate the outbound URL before resolution. Resolve it against the proposal's stored company identity, project the deterministic result with the same helper used by `_post_process`, then compare-and-swap with the store method from Step 1. Do not run HTTP, DNS, or connector preview calls while the Scout ledger lock is held.

- [ ] **Step 6: Add the route while preserving old approve callers**

```python
@router.post(
    "/scout/sessions/{session_id}/proposals/{proposal_id}/approve",
    response_model=ScoutSessionOut,
)
def approve_scout_proposal(
    session_id: str,
    proposal_id: str,
    request: Request,
    payload: ScoutApproveIn | None = None,
    settings: Settings = Depends(get_settings_dep),
):
    connectors_path, search_path = _config_paths(request)
    try:
        return ScoutSessionOut.model_validate(
            approve_proposal(
                _workspace_root(request),
                session_id,
                proposal_id,
                config_store=get_config_store(request),
                connectors_path=connectors_path,
                search_path=search_path,
                browser_enabled=settings.browser_enabled,
                manual_confirmation=payload.manual_confirmation if payload else False,
            )
        )
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.post(
    "/scout/sessions/{session_id}/proposals/{proposal_id}/resolve",
    response_model=ScoutSessionOut,
)
def resolve_scout_proposal(
    session_id: str,
    proposal_id: str,
    payload: ScoutResolveSourceIn,
    request: Request,
    settings: Settings = Depends(get_settings_dep),
):
    _, search_path = _config_paths(request)
    try:
        return ScoutSessionOut.model_validate(
            resolve_proposal_source(
                _workspace_root(request),
                session_id,
                proposal_id,
                url=str(payload.url),
                search_path=search_path,
                browser_enabled=settings.browser_enabled,
            )
        )
    except ScoutProposalChangedError as exc:
        raise ApiException(409, "CONFLICT", str(exc)) from exc
    except ValueError as exc:
        raise _value_error(exc) from exc
```

Import `ScoutProposalChangedError` from the store, `resolve_proposal_source` from the service, and the new request schemas through the router's existing import blocks. Preserve the current `_value_error()` conventions: missing proposal/session is 404, stale or blocked state is 409, and malformed input is 422. Keep approve's body optional for compatibility.

- [ ] **Step 7: Run the backend boundary tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_scout_store.py tests/test_scout_service.py tests/api/test_scout_router.py tests/api/test_schemas_scout.py -q`

Expected: PASS; there is no service or API path that normally adds an unverified source.

- [ ] **Step 8: Commit the backend enforcement boundary**

```bash
git add src/resume_agent/discovery/scout_store.py src/resume_agent/services/scout.py src/resume_agent/api/schemas/scout.py src/resume_agent/api/routers/scout.py tests/test_scout_store.py tests/test_scout_service.py tests/api/test_scout_router.py tests/api/test_schemas_scout.py
git commit -m "feat: gate Scout source approval on verification"
```

### Task 8: Regenerate and lock the API contracts

**Files:**
- Modify: `contracts/openapi.json`
- Modify: `contracts/ts/api.ts`
- Modify: `web/src/lib/api/schema.ts`
- Test: `tests/api/test_openapi_contract.py`

- [ ] **Step 1: Add failing OpenAPI assertions**

Assert that the generated document contains:

- `POST /api/scout/sessions/{session_id}/proposals/{proposal_id}/resolve` with required `ScoutResolveSourceIn`;
- an optional approve body referencing `ScoutApproveIn`;
- `manualConfirmation`, evidence, resolution status, reason code, and coverage fields;
- `conflict` in the proposal check enum.

- [ ] **Step 2: Run the contract test and confirm the checked-in snapshot is stale**

Run: `.venv\Scripts\python.exe -m pytest tests/api/test_openapi_contract.py -q`

Expected: FAIL because the generated snapshots do not yet include the new API surface.

- [ ] **Step 3: Regenerate all three checked-in contracts on Windows**

Run:

```powershell
.venv\Scripts\python.exe scripts\export_openapi.py
npx.cmd --yes openapi-typescript contracts/openapi.json -o contracts/ts/api.ts
Copy-Item -LiteralPath contracts/ts/api.ts -Destination web/src/lib/api/schema.ts
```

Do not hand-edit generated declarations.

- [ ] **Step 4: Verify generated parity and schema assertions**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/api/test_openapi_contract.py -q
Compare-Object (Get-Content contracts/ts/api.ts) (Get-Content web/src/lib/api/schema.ts)
```

Use `tests/api/test_openapi_contract.py` in the first command. `Compare-Object` must produce no output, proving the SPA schema is an exact copy of the generated contract.

- [ ] **Step 5: Commit the generated API surface**

```bash
git add contracts/openapi.json contracts/ts/api.ts web/src/lib/api/schema.ts tests/api/test_openapi_contract.py
git commit -m "chore: regenerate Scout verification contracts"
```

### Task 9: Make frontend mutations and addability predicates verification-aware

**Files:**
- Modify: `web/src/features/scout/use-scout.ts`
- Modify: `web/src/features/scout/proposals.ts`
- Test: `web/src/features/scout/use-scout.test.tsx`
- Create: `web/src/features/scout/proposals.test.ts`
- Test: `web/src/features/scout/ProposalRail.test.tsx`

- [ ] **Step 1: Write failing query-hook tests**

Require `useApproveScoutProposal()` to omit the body for normal approval and send the generated camel-case request `{ manualConfirmation: true }` only for an override. Require `useResolveScoutProposal()` to post `{ url }` to the new resolve route, invalidate the session query on success, and surface 400/409 response text without losing the current proposal.

- [ ] **Step 2: Write failing pure-predicate tests**

Add and exhaustively test:

```typescript
export function canAddProposal(row: ScoutProposal): boolean
export function canManuallyConfirm(
  row: ScoutProposal,
  scrapeAvailable: boolean,
): boolean
export function verificationLabel(row: ScoutProposal):
  | "Verified"
  | "Unverified"
  | "Ownership conflict"
  | null
```

`canAddProposal` permits validated sources and existing eligible non-source proposals only. `canManuallyConfirm` permits unverified known-ATS sources, plus generic unverified URLs only when scrape support is available. It always denies conflicts, failures, duplicates, avoided sources, and resolved proposals.

- [ ] **Step 3: Implement the typed mutations from generated operations**

Use types from `web/src/lib/api/schema.ts`; do not redeclare request or response shapes. Keep the existing optimistic/invalidating behavior for approve and reject. The resolve mutation must not optimistically label a source verified.

- [ ] **Step 4: Route every addability decision through the predicates**

Replace component-local checks in the proposal rail and batch-selection logic. The batch payload must exclude every unverified source even when manual confirmation is individually available. Preserve current selection for eligible search-term proposals.

- [ ] **Step 5: Run the hook and predicate tests**

Run: `npm.cmd --prefix web run test:run -- src/features/scout/use-scout.test.tsx src/features/scout/proposals.test.ts src/features/scout/ProposalRail.test.tsx`

Expected: PASS; no unverified source reaches normal or batch approval.

- [ ] **Step 6: Commit the frontend policy layer**

```bash
git add web/src/features/scout/use-scout.ts web/src/features/scout/proposals.ts web/src/features/scout/use-scout.test.tsx web/src/features/scout/proposals.test.ts web/src/features/scout/ProposalRail.test.tsx
git commit -m "feat: enforce Scout verification in frontend actions"
```

### Task 10: Add retry and explicit manual-confirmation UI

**Files:**
- Create: `web/src/features/scout/SourceVerificationActions.tsx`
- Create: `web/src/features/scout/SourceVerificationActions.test.tsx`
- Modify: `web/src/features/scout/ProposalCard.tsx`
- Modify: `web/src/features/scout/ProposalCard.test.tsx`
- Modify: `web/src/features/scout/ProposalRail.test.tsx`
- Modify: `web/e2e/scout-ledger.spec.ts`

- [ ] **Step 1: Write failing accessible interaction tests**

Cover these user-visible states:

- verified source: `Verified` badge, canonical board link, ordinary `Add` action;
- unverified source: `Unverified` badge, reason text, `Open board`, `Try another URL`, and eligible `Confirm & add anyway`;
- ownership conflict: conflict badge, evidence summary, retry action, no manual override;
- unsupported generic URL without browser support: retry remains available, manual override absent;
- batch mode: unverified rows cannot be selected or approved.

Test keyboard activation, dialog naming/description, error announcement with `role="alert"`, focus return after close, and visible focus styling on every new control.

- [ ] **Step 2: Build the focused action component**

`SourceVerificationActions` receives the proposal, browser capability, pending flags, and callbacks. Its URL form initializes from `canonicalBoardUrl ?? requestedUrl ?? url`, validates an absolute HTTP(S) URL client-side, and calls the resolve mutation. A successful resolution closes the form and lets query invalidation redraw the card; a failure preserves the typed URL and announces the error.

- [ ] **Step 3: Require an explicit confirmation ceremony**

Use the repository's Base UI `AlertDialog` and `Checkbox`. The dialog must display the exact company, URL, detected ATS or `Unknown`, and reason the board is unverified. Include an unchecked affirmation such as “I manually confirmed this is the company’s official job board.” Keep the destructive-looking confirmation button disabled until checked. On close or URL replacement, reset the checkbox and pending error.

- [ ] **Step 4: Integrate with the proposal card and rail**

Render the ordinary `Add` control only when `canAddProposal()` is true. Render manual confirmation only when `canManuallyConfirm()` is true. `Open board` uses `target="_blank"` with `rel="noreferrer"`. Display compact evidence and searched/unsearched-family details without making them prerequisites for retry. Preserve existing reject, duplicate, avoid, responsive, and loading behavior.

- [ ] **Step 5: Extend the Scout ledger browser test**

Mock the resolve route and optional approve body. Prove that an unverified proposal cannot use ordinary or batch add, URL replacement can produce a verified card, and manual confirmation sends exactly `{ manualConfirmation: true }` only after affirmation.

- [ ] **Step 6: Run focused component and browser tests**

Run:

```powershell
npm.cmd --prefix web run test:run -- src/features/scout/SourceVerificationActions.test.tsx src/features/scout/ProposalCard.test.tsx src/features/scout/ProposalRail.test.tsx
npm.cmd --prefix web run e2e -- scout-ledger.spec.ts
```

Expected: PASS with no accessibility-query warnings and no unverified normal-add path.

- [ ] **Step 7: Commit the guarded confirmation experience**

```bash
git add web/src/features/scout/SourceVerificationActions.tsx web/src/features/scout/SourceVerificationActions.test.tsx web/src/features/scout/ProposalCard.tsx web/src/features/scout/ProposalCard.test.tsx web/src/features/scout/ProposalRail.test.tsx web/e2e/scout-ledger.spec.ts
git commit -m "feat: add guarded Scout source confirmation"
```

### Task 11: Add offline golden coverage and an opt-in live accuracy evaluation

**Files:**
- Create: `evals/scout_source_cases.json`
- Create: `evals/scout_source_eval.py`
- Create: `evals/run_scout_source_eval.py`
- Create: `tests/eval/test_scout_source_eval.py`
- Create: `tests/eval/test_scout_source_cases.py`

- [ ] **Step 1: Write the reviewed live-case manifest**

Add these seed cases with `evidence_checked_at: "2026-08-14"`:

```json
[
  {
    "company": "Intuitive Surgical",
    "official_careers_url": "https://careers.intuitive.com/en/",
    "expected_ats": "smartrecruiters",
    "expected_board_url": "https://careers.smartrecruiters.com/intuitive"
  },
  {
    "company": "Tempus",
    "official_careers_url": "https://www.tempus.com/careers/",
    "expected_ats": "workday",
    "expected_board_url": "https://tempus.wd5.myworkdayjobs.com/Tempus_Careers"
  }
]
```

Manifest tests validate unique company names, supported ATS values, canonical HTTPS URLs, and a parseable review date. Fixture-based resolver tests from Task 4 remain the required CI accuracy proof; the live values are deliberately refreshable evidence, not timeless constants.

- [ ] **Step 2: Write failing evaluator tests with a fake resolver**

Require a structured result per case with expected/actual ATS and URL, resolution status, reason, elapsed time, and pass/fail. Assert the suite fails when a result is wrong or merely unverified, succeeds only for exact normalized ATS+URL matches, and reports rather than aborts individual network errors.

- [ ] **Step 3: Implement the read-only evaluator and CLI**

The evaluator calls the production deterministic resolver and never mutates Scout sessions or source configuration. The CLI accepts `--cases`, `--output`, and `--timeout-seconds`, writes one JSON report, prints a compact summary, and exits nonzero on mismatches. It must be explicitly invoked; do not put the live-network command in default CI or unit-test targets.

- [ ] **Step 4: Run the offline evaluator tests**

Run: `.venv\Scripts\python.exe -m pytest tests/eval/test_scout_source_eval.py tests/eval/test_scout_source_cases.py tests/test_scout_resolution_golden.py -q`

Expected: PASS without internet access.

- [ ] **Step 5: Optionally refresh the two live cases before release**

Run: `.venv\Scripts\python.exe evals/run_scout_source_eval.py --cases evals/scout_source_cases.json --output .artifacts/scout-source-eval.json --timeout-seconds 20`

Expected when the public boards remain current: exit 0 and two exact matches. A rate limit or site change is a release-review signal, not permission to rewrite the expected values automatically.

- [ ] **Step 6: Commit the evaluation harness**

```bash
git add evals/scout_source_cases.json evals/scout_source_eval.py evals/run_scout_source_eval.py tests/eval/test_scout_source_eval.py tests/eval/test_scout_source_cases.py
git commit -m "test: add Scout ATS accuracy evaluation"
```

### Task 12: Run release-level verification and inspect the safety invariants

**Files:**
- Verify only; modify the smallest owning file if a check exposes a regression.

- [ ] **Step 1: Audit the implementation for forbidden fallback paths**

Run:

```powershell
rg -n "check_source|check == ['\"]unverified['\"].*add|manual_confirmation" src tests web/src
rg -n "jobs\.smartrecruiters\.com|careers\.smartrecruiters\.com" src tests evals
```

Review every match. There must be no live `check_source` tool, no ordinary-add branch for unverified sources, no client-authored audit details, and no catalog drift between the resolver and connector registry. Historical migration fixtures may retain old SmartRecruiters URLs when the test explicitly labels them as legacy input.

- [ ] **Step 2: Run the complete focused backend proof**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_source_resolution_catalog.py tests/test_source_resolution_identity.py tests/test_source_resolution_crawler.py tests/test_source_resolution_resolver.py tests/test_scout_resolution_golden.py tests/test_scout_store.py tests/test_scout_service.py tests/api/test_scout_router.py tests/api/test_schemas_scout.py tests/test_scout.py tests/test_llm_runner_search_equipped.py tests/test_prompt_registry.py tests/api/test_openapi_contract.py tests/eval/test_scout_source_eval.py tests/eval/test_scout_source_cases.py -q
```

Expected: PASS.

- [ ] **Step 3: Run the full Python suite and static checks**

Run:

```powershell
.venv\Scripts\python.exe -m pytest -q
uv run ruff check .
```

Expected: both exit 0. A timeout is incomplete verification and must be reported as such.

- [ ] **Step 4: Run all frontend tests, lint, and production build**

Run:

```powershell
npm.cmd --prefix web run test:run
npm.cmd --prefix web run lint
npm.cmd --prefix web run build
```

Expected: all commands exit 0.

- [ ] **Step 5: Inspect repository and generated-file cleanliness**

Run:

```powershell
Compare-Object (Get-Content contracts/ts/api.ts) (Get-Content web/src/lib/api/schema.ts)
git diff --check
git status --short
```

Expected: `Compare-Object` and `git diff --check` produce no output. `git status --short` contains no unintended files; any remaining entries are deliberate implementation changes or pre-existing user work.

- [ ] **Step 6: Record the release evidence**

In the implementation handoff, report exact command outcomes, the two offline golden results, whether the optional live evaluation was run, and any unresolved network/rate-limit observation. Do not describe a source as verified unless deterministic ownership evidence passed.
