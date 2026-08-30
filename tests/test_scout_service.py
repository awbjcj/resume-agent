from dataclasses import dataclass
import threading
import time
from typing import Literal, cast

import pytest

from resume_agent.api.schemas.config import SearchConfigDoc
from resume_agent.discovery.scout import ScoutTurnDraft
from resume_agent.discovery.scout_store import (
    ScoutProposal,
    ScoutTurnRecord,
    SourcePayload,
    TermPayload,
    create_session_from_turn,
    end_session,
    load_session,
)
from resume_agent.discovery.source_resolution.models import (
    CompanySourceResolution,
    ResolutionStatus,
    SourceEvidence,
)
from resume_agent.discovery.source_resolution.resolver import resolution_cache_key
from resume_agent.discovery.source_resolution.search import SearchCoverage
from resume_agent.services import scout as service
from resume_agent.services.config_store import YamlConfigStore
from resume_agent.services.scout_intelligence import (
    ScoutCompanyIntelligenceSnapshot,
)
from resume_agent.sessions.stream import (
    Completed,
    TextDelta,
    ToolCompleted,
    ToolStarted,
)


class Reporter:
    def begin(self, total, label, **kwargs):
        pass

    def step(self, current, **kwargs):
        pass

    def checkpoint(self):
        pass


@dataclass
class Result:
    content: object


class Formatter:
    def __init__(self, turn: ScoutTurnDraft):
        self.turn = turn

    def run(self, prompt: str) -> Result:
        return Result(self.turn)

    async def arun(self, prompt: str) -> Result:
        return self.run(prompt)


class StreamingScout:
    def __init__(self, text="Found one option."):
        self.text = text
        self.prompts = []

    def stream(self, prompt):
        self.prompts.append(prompt)
        yield TextDelta(self.text)
        yield ToolStarted("t1", "web_search", "AI infrastructure")
        yield ToolCompleted("t1", "web_search", "results")
        yield Completed(Result(self.text))

    def run(self, prompt):
        self.prompts.append(prompt)
        return Result(self.text)

    async def arun(self, prompt):
        return self.run(prompt)


CheckStatus = Literal[
    "validated", "unverified", "conflict", "failed", "duplicate", "avoid", "new"
]


def source_proposal(
    company: str = "Modal", check: CheckStatus = "validated"
) -> ScoutProposal:
    return ScoutProposal(
        kind="source",
        source=SourcePayload(
            company=company, url=f"https://{company.casefold()}.example/jobs"
        ),
        check=check,
    )


def term_proposal(value="inference serving"):
    return ScoutProposal(kind="search_term", term=TermPayload(value=value), check="new")


def test_post_process_reuses_the_company_and_board_resolution(tmp_path):
    resolution = CompanySourceResolution(
        company="Modal",
        requested_url="https://jobs.lever.co/modal",
        canonical_board_url="https://jobs.lever.co/modal",
        ats="lever",
        token="modal",
        role_count=4,
        status="verified",
        reason_code="VERIFIED_PROVIDER_METADATA",
    )
    cache = {resolution_cache_key("Modal", resolution.requested_url): resolution}

    proposals = service._post_process(
        Reporter(),
        [
            ScoutTurnDraft.model_validate(
                {
                    "message": "Found Modal.",
                    "proposals": [
                        {
                            "kind": "source",
                            "source": {
                                "company": "Modal",
                                "url": "https://jobs.lever.co/modal",
                            },
                        }
                    ],
                }
            ).proposals[0]
        ],
        session={"proposals": []},
        connectors_path=str(tmp_path / "connectors.yaml"),
        search_path=str(tmp_path / "search.yaml"),
        resolution_cache=cache,
        resolve_source=lambda *_args: pytest.fail("source was resolved twice"),
    )

    assert proposals[0].check == "validated"
    assert proposals[0].source is not None
    assert proposals[0].source.token == "modal"


def test_streamed_prose_is_stored_and_source_is_authoritatively_resolved(
    monkeypatch, tmp_path
):
    class Resolver:
        def __init__(self, _search_path):
            pass

        def resolve(self, company, candidate_url):
            return CompanySourceResolution(
                company=company,
                requested_url=candidate_url,
                canonical_board_url="https://jobs.lever.co/modal",
                ats="lever",
                token="modal",
                role_count=4,
                status="verified",
                reason_code="VERIFIED_PROVIDER_METADATA",
            )

    monkeypatch.setattr(service, "CompanySourceResolver", Resolver)
    sink = _Sink()
    view = service.run_start_turn(
        Reporter(),
        workspace_root=tmp_path,
        session_id="s1",
        message="AI infra",
        connectors_path=str(tmp_path / "config" / "connectors.yaml"),
        search_path=str(tmp_path / "config" / "search.yaml"),
        profile_dir=tmp_path / "profile",
        browser_enabled=False,
        sink=sink,
        scout_agent=StreamingScout(),
        formatter_agent=Formatter(
            ScoutTurnDraft.model_validate(
                {
                    "message": "Formatter wording",
                    "proposals": [
                        {
                            "kind": "source",
                            "source": {
                                "company": "Modal",
                                "url": "https://modal.example/jobs",
                            },
                        }
                    ],
                }
            )
        ),
    )
    assert view["turns"][-1]["text"] == "Found one option."
    assert view["proposals"][0]["check"] == "validated"
    assert view["proposals"][0]["source"]["url"] == "https://jobs.lever.co/modal"
    assert view["proposals"][0]["source"]["roleCount"] == 4
    assert (
        "".join(event.text for event in sink.events if isinstance(event, TextDelta))
        == "Found one option."
    )
    assert [
        type(event).__name__
        for event in sink.events
        if isinstance(event, (ToolStarted, ToolCompleted))
    ] == ["ToolStarted", "ToolCompleted"]


def test_post_process_never_validates_a_live_unowned_board(tmp_path):
    result = CompanySourceResolution(
        company="Tempus",
        requested_url="https://jobs.lever.co/tempus",
        canonical_board_url="https://jobs.lever.co/tempus",
        ats="lever",
        status="unverified",
        reason_code="OWNERSHIP_NOT_PROVEN",
    )
    draft = ScoutTurnDraft.model_validate(
        {
            "message": "Found Tempus.",
            "proposals": [
                {
                    "kind": "source",
                    "source": {
                        "company": "Tempus",
                        "url": result.requested_url,
                    },
                }
            ],
        }
    ).proposals[0]

    proposals = service._post_process(
        Reporter(),
        [draft],
        session={"proposals": []},
        connectors_path=str(tmp_path / "connectors.yaml"),
        search_path=str(tmp_path / "search.yaml"),
        resolve_source=lambda _company, _url: result,
    )

    assert proposals[0].check == "unverified"
    assert proposals[0].source is not None
    assert proposals[0].source.resolution_reason == "OWNERSHIP_NOT_PROVEN"


def test_interrupted_search_only_downgrades_unresolved_sources(tmp_path):
    verified = CompanySourceResolution(
        company="Intuitive Surgical",
        requested_url="https://careers.smartrecruiters.com/intuitive",
        canonical_board_url="https://careers.smartrecruiters.com/intuitive",
        ats="smartrecruiters",
        status="verified",
        reason_code="VERIFIED_FIRST_PARTY",
    )
    unresolved = CompanySourceResolution(
        company="Tempus",
        requested_url="https://tempus.wd5.myworkdayjobs.com/Tempus_Careers",
        canonical_board_url="https://tempus.wd5.myworkdayjobs.com/Tempus_Careers",
        ats="workday",
        status="unverified",
        reason_code="OWNERSHIP_NOT_PROVEN",
    )
    drafts = ScoutTurnDraft.model_validate(
        {
            "message": "Found two companies.",
            "proposals": [
                {
                    "kind": "source",
                    "source": {
                        "company": verified.company,
                        "url": verified.requested_url,
                    },
                },
                {
                    "kind": "source",
                    "source": {
                        "company": unresolved.company,
                        "url": unresolved.requested_url,
                    },
                },
            ],
        }
    ).proposals
    coverage = SearchCoverage(
        searched_families=["smartrecruiters", "workday"],
        unsearched_families=["lever"],
        interruption_reason="SEARCH_RATE_LIMITED",
    )

    proposals = service._post_process(
        Reporter(),
        drafts,
        session={"proposals": []},
        connectors_path=str(tmp_path / "connectors.yaml"),
        search_path=str(tmp_path / "search.yaml"),
        resolve_source=lambda company, _url: (
            verified if company == verified.company else unresolved
        ),
        search_coverage=coverage,
    )

    assert [row.check for row in proposals] == ["validated", "unverified"]
    assert proposals[0].source is not None
    assert proposals[0].source.resolution_reason == "VERIFIED_FIRST_PARTY"
    assert proposals[1].source is not None
    assert proposals[1].source.resolution_reason == "SEARCH_RATE_LIMITED"


def test_post_process_limits_concurrent_company_resolutions_to_four(tmp_path):
    active = 0
    peak = 0
    guard = threading.Lock()

    def resolve(company: str, url: str) -> CompanySourceResolution:
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
        time.sleep(0.03)
        with guard:
            active -= 1
        return CompanySourceResolution(
            company=company,
            requested_url=url,
            canonical_board_url=url,
            status="unverified",
            reason_code="OWNERSHIP_NOT_PROVEN",
        )

    drafts = ScoutTurnDraft.model_validate(
        {
            "message": "Found candidates.",
            "proposals": [
                {
                    "kind": "source",
                    "source": {
                        "company": f"Company {index}",
                        "url": f"https://company-{index}.example/jobs",
                    },
                }
                for index in range(6)
            ],
        }
    ).proposals

    service._post_process(
        Reporter(),
        drafts,
        session={"proposals": []},
        connectors_path=str(tmp_path / "connectors.yaml"),
        search_path=str(tmp_path / "search.yaml"),
        resolve_source=resolve,
    )

    assert peak == 4


class _Sink:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)

    def close(self):
        pass


def test_dismissed_feedback_is_in_next_prompt(tmp_path):
    create_session_from_turn(
        tmp_path,
        "s1",
        goal="AI infra",
        user_text="AI infra",
        scout_turn=ScoutTurnRecord(role="scout", text="First"),
        proposals=[source_proposal("Scale-AI")],
    )
    service.dismiss_proposal(
        tmp_path, "s1", "p1", reason="too big", browser_enabled=False
    )
    runner = StreamingScout("Here are smaller teams.")
    service.run_message_turn(
        Reporter(),
        workspace_root=tmp_path,
        session_id="s1",
        message="find smaller ones",
        connectors_path=str(tmp_path / "config" / "connectors.yaml"),
        search_path=str(tmp_path / "config" / "search.yaml"),
        profile_dir=tmp_path / "profile",
        browser_enabled=False,
        scout_agent=runner,
        formatter_agent=Formatter(ScoutTurnDraft(message="Here are smaller teams.")),
    )
    assert "DISMISSED — DO NOT PROPOSE AGAIN" in runner.prompts[0]
    assert "Scale-AI — user said: too big" in runner.prompts[0]


def test_repeated_source_and_term_are_stored_as_duplicates(tmp_path):
    create_session_from_turn(
        tmp_path,
        "s1",
        goal="AI infra",
        user_text="AI infra",
        scout_turn=ScoutTurnRecord(role="scout", text="First"),
        proposals=[source_proposal(), term_proposal()],
    )
    turn = ScoutTurnDraft.model_validate(
        {
            "message": "Repeated",
            "proposals": [
                {
                    "kind": "source",
                    "source": {"company": "Modal", "url": "https://other.example/jobs"},
                },
                {"kind": "search_term", "term": {"value": "Inference Serving"}},
            ],
        }
    )
    view = service.run_message_turn(
        Reporter(),
        workspace_root=tmp_path,
        session_id="s1",
        message="more",
        connectors_path=str(tmp_path / "connectors.yaml"),
        search_path=str(tmp_path / "search.yaml"),
        profile_dir=tmp_path,
        browser_enabled=False,
        scout_agent=StreamingScout("Repeated"),
        formatter_agent=Formatter(turn),
    )
    assert [row["check"] for row in view["proposals"][-2:]] == [
        "duplicate",
        "duplicate",
    ]


def test_term_approval_preserves_unrelated_fields(tmp_path):
    create_session_from_turn(
        tmp_path,
        "s1",
        goal="AI infra",
        user_text="AI infra",
        scout_turn=ScoutTurnRecord(role="scout", text="First"),
        proposals=[term_proposal()],
    )
    store = YamlConfigStore(tmp_path / "config")
    store.put("search", SearchConfigDoc(keywords=["python"], min_salary=180_000))
    view = service.approve_proposal(
        tmp_path,
        "s1",
        "p1",
        config_store=store,
        connectors_path=str(tmp_path / "config" / "connectors.yaml"),
        search_path=str(tmp_path / "config" / "search.yaml"),
        browser_enabled=False,
    )
    saved = cast(SearchConfigDoc, store.get("search"))
    assert saved.keywords == ["python", "inference serving"]
    assert saved.min_salary == 180_000
    assert view["proposals"][0]["status"] == "added"


def _seed_source_for_approval(
    tmp_path,
    *,
    check: CheckStatus,
    ats: str | None = "lever",
) -> None:
    resolution_status: dict[CheckStatus, ResolutionStatus] = {
        "validated": "verified",
        "unverified": "unverified",
        "conflict": "conflict",
        "failed": "failed",
    }
    create_session_from_turn(
        tmp_path,
        "s1",
        goal="AI infra",
        user_text="AI infra",
        scout_turn=ScoutTurnRecord(role="scout", text="First"),
        proposals=[
            ScoutProposal(
                kind="source",
                source=SourcePayload(
                    company="Acme",
                    url="https://jobs.lever.co/acme"
                    if ats
                    else "https://acme.example/careers",
                    ats=ats,
                    resolution_status=resolution_status.get(check),
                    resolution_reason="OWNERSHIP_NOT_PROVEN",
                    company_intelligence_status="ready",
                    company_intelligence_version=3,
                ),
                check=check,
            )
        ],
    )


def test_normal_approval_requires_a_verified_source(monkeypatch, tmp_path):
    _seed_source_for_approval(tmp_path, check="unverified")
    monkeypatch.setattr(service, "add_source", lambda **_kwargs: None)

    with pytest.raises(ValueError, match="manual confirmation required"):
        service.approve_proposal(
            tmp_path,
            "s1",
            "p1",
            config_store=YamlConfigStore(tmp_path / "config"),
            connectors_path=str(tmp_path / "connectors.yaml"),
            search_path=str(tmp_path / "search.yaml"),
            browser_enabled=True,
        )


def test_manual_confirmation_adds_unverified_known_ats_and_audits(
    monkeypatch, tmp_path
):
    _seed_source_for_approval(tmp_path, check="unverified", ats="lever")
    calls = []
    monkeypatch.setattr(service, "add_source", lambda **kwargs: calls.append(kwargs))

    view = service.approve_proposal(
        tmp_path,
        "s1",
        "p1",
        config_store=YamlConfigStore(tmp_path / "config"),
        connectors_path=str(tmp_path / "connectors.yaml"),
        search_path=str(tmp_path / "search.yaml"),
        browser_enabled=False,
        manual_confirmation=True,
    )

    assert calls[0]["provider"] == "auto"
    assert (
        view["proposals"][0]["manualConfirmation"]["url"]
        == "https://jobs.lever.co/acme"
    )


def test_manual_confirmation_requires_a_browser_for_generic_sources(
    monkeypatch, tmp_path
):
    _seed_source_for_approval(tmp_path, check="unverified", ats=None)
    monkeypatch.setattr(
        service, "add_source", lambda **_kwargs: pytest.fail("must not add")
    )

    with pytest.raises(ValueError, match="requires a local browser"):
        service.approve_proposal(
            tmp_path,
            "s1",
            "p1",
            config_store=YamlConfigStore(tmp_path / "config"),
            connectors_path=str(tmp_path / "connectors.yaml"),
            search_path=str(tmp_path / "search.yaml"),
            browser_enabled=False,
            manual_confirmation=True,
        )


@pytest.mark.parametrize("check", ["conflict", "failed"])
def test_conflict_and_failed_sources_cannot_be_manually_confirmed(
    monkeypatch, tmp_path, check
):
    _seed_source_for_approval(tmp_path, check=check)
    monkeypatch.setattr(
        service, "add_source", lambda **_kwargs: pytest.fail("must not add")
    )

    with pytest.raises(ValueError, match="not approvable"):
        service.approve_proposal(
            tmp_path,
            "s1",
            "p1",
            config_store=YamlConfigStore(tmp_path / "config"),
            connectors_path=str(tmp_path / "connectors.yaml"),
            search_path=str(tmp_path / "search.yaml"),
            browser_enabled=True,
            manual_confirmation=True,
        )


def test_re_resolve_replaces_only_the_pending_exact_source_url(monkeypatch, tmp_path):
    _seed_source_for_approval(tmp_path, check="unverified")
    monkeypatch.setattr(service, "validate_public_url", lambda _url: None)

    class Resolver:
        def resolve(self, company, candidate_url):
            return CompanySourceResolution(
                company=company,
                requested_url=candidate_url,
                canonical_board_url="https://tempus.wd5.myworkdayjobs.com/Tempus_Careers",
                ats="workday",
                status="verified",
                reason_code="VERIFIED_PROVIDER_METADATA",
            )

    view = service.resolve_proposal_source(
        tmp_path,
        "s1",
        "p1",
        url="https://tempus.example/careers",
        search_path=str(tmp_path / "search.yaml"),
        browser_enabled=False,
        resolver=Resolver(),
    )

    proposal = view["proposals"][0]
    assert proposal["check"] == "validated"
    assert (
        proposal["source"]["url"]
        == "https://tempus.wd5.myworkdayjobs.com/Tempus_Careers"
    )
    assert proposal["source"]["requestedUrl"] == "https://tempus.example/careers"
    assert proposal["source"]["companyIntelligenceStatus"] == "ready"
    assert proposal["source"]["companyIntelligenceVersion"] == 3


def test_server_rejects_non_approvable_source_and_allows_resolution_after_end(tmp_path):
    create_session_from_turn(
        tmp_path,
        "s1",
        goal="AI infra",
        user_text="AI infra",
        scout_turn=ScoutTurnRecord(role="scout", text="First"),
        proposals=[source_proposal(check="failed")],
    )
    end_session(tmp_path, "s1", "Done")
    with pytest.raises(ValueError, match="not approvable"):
        service.approve_proposal(
            tmp_path,
            "s1",
            "p1",
            config_store=YamlConfigStore(tmp_path / "config"),
            connectors_path=str(tmp_path / "connectors.yaml"),
            search_path=str(tmp_path / "search.yaml"),
            browser_enabled=False,
        )
    dismissed = service.dismiss_proposal(
        tmp_path, "s1", "p1", reason="broken", browser_enabled=False
    )
    assert dismissed["proposals"][0]["status"] == "dismissed"
    assert load_session(tmp_path, "s1")["status"] == "ended"


def test_session_view_projects_source_resolution_fields(tmp_path):
    create_session_from_turn(
        tmp_path,
        "s1",
        goal="AI infra",
        user_text="AI infra",
        scout_turn=ScoutTurnRecord(role="scout", text="First"),
        proposals=[
            ScoutProposal(
                kind="source",
                source=SourcePayload(
                    company="Acme",
                    url="https://jobs.lever.co/acme",
                    ats="lever",
                    resolution_status="unverified",
                    resolution_reason="OWNERSHIP_NOT_PROVEN",
                    evidence=[
                        SourceEvidence(
                            kind="candidate",
                            source_url="https://acme.example/careers",
                        )
                    ],
                    searched_families=["lever"],
                    unsearched_families=["workday"],
                    company_intelligence_status="ready",
                    company_intelligence_version=3,
                ),
                check="unverified",
            )
        ],
    )

    source = service.session_view(tmp_path, "s1", browser_enabled=False)["proposals"][
        0
    ]["source"]

    assert source["resolutionStatus"] == "unverified"
    assert source["resolutionReason"] == "OWNERSHIP_NOT_PROVEN"
    assert source["evidence"][0]["kind"] == "candidate"
    assert source["searchedFamilies"] == ["lever"]
    assert source["unsearchedFamilies"] == ["workday"]
    assert source["companyIntelligenceStatus"] == "ready"
    assert source["companyIntelligenceVersion"] == 3


class UnparsableFormatter:
    """A formatter whose provider returned prose instead of the schema."""

    def run(self, prompt: str) -> Result:
        return Result("Sure! Here is the JSON you asked for:")

    async def arun(self, prompt: str) -> Result:
        return self.run(prompt)


def test_unparsable_formatter_keeps_the_reply_the_user_already_watched(
    tmp_path, caplog
):
    # agno reports "could not coerce into output_schema" by handing back a raw
    # str, which expect_schema raises as UnparsedAgentOutput -- a TypeError, so
    # the TurnRejected fallback never saw it. The researcher's answer has
    # already streamed into the chat by then, so failing the run deletes a reply
    # the user just read. Degrade like every other formatter failure, but log
    # the diagnostic so the provider fault stays visible.
    view = service.run_start_turn(
        Reporter(),
        workspace_root=tmp_path,
        session_id="s1",
        message="AI infra",
        connectors_path=str(tmp_path / "connectors.yaml"),
        search_path=str(tmp_path / "search.yaml"),
        profile_dir=tmp_path,
        browser_enabled=False,
        scout_agent=StreamingScout("Found one option."),
        formatter_agent=UnparsableFormatter(),
    )
    assert view["turns"][-1]["text"] == "Found one option."
    assert view["turns"][-1]["notice"] == service._TURN_OMITTED_NOTICE
    assert view["proposals"] == []
    assert any(
        "Expected ScoutTurnDraft" in record.getMessage() for record in caplog.records
    )


def test_a_posting_url_reuses_its_company_and_board_resolution(tmp_path):
    """The agent finds a posting; the workspace must end up with the board.

    This also pins cache alignment: the resolver tool and post-processing have
    to normalize the company/board key identically, or one source is resolved
    twice.
    """
    posting = (
        "https://phinia.wd5.myworkdayjobs.com/en-US/PHINIA_Careers/job/"
        "Potting-and-Dispense-System-Expert_R2026-0020?utm_source=openai"
    )
    root = "https://phinia.wd5.myworkdayjobs.com/PHINIA_Careers"
    resolution = CompanySourceResolution(
        company="PHINIA",
        requested_url=root,
        canonical_board_url=root,
        ats="workday",
        role_count=7,
        status="verified",
        reason_code="VERIFIED_FIRST_PARTY",
    )
    cache = {resolution_cache_key("PHINIA", posting): resolution}

    proposals = service._post_process(
        Reporter(),
        [
            ScoutTurnDraft.model_validate(
                {
                    "message": "Found PHINIA.",
                    "proposals": [
                        {
                            "kind": "source",
                            "source": {"company": "PHINIA", "url": posting},
                        }
                    ],
                }
            ).proposals[0]
        ],
        session={"proposals": []},
        connectors_path=str(tmp_path / "connectors.yaml"),
        search_path=str(tmp_path / "search.yaml"),
        resolution_cache=cache,
        resolve_source=lambda *_args: pytest.fail("source was resolved twice"),
    )

    assert proposals[0].source is not None
    assert proposals[0].source.url == root
    assert proposals[0].check == "validated"


def test_post_process_attaches_server_owned_company_intelligence_metadata(tmp_path):
    resolution = CompanySourceResolution(
        company="Acme, Inc.",
        requested_url="https://jobs.lever.co/acme",
        canonical_board_url="https://jobs.lever.co/acme",
        ats="lever",
        status="verified",
        reason_code="VERIFIED_PROVIDER_METADATA",
    )

    class IntelligenceLookup:
        def lookup_many(self, companies):
            assert companies == ["Acme, Inc."]
            return {
                "acme": ScoutCompanyIntelligenceSnapshot(
                    status="stale",
                    normalized_company="acme",
                    display_company="Acme",
                    version_number=4,
                )
            }

    proposals = service._post_process(
        Reporter(),
        [
            ScoutTurnDraft.model_validate(
                {
                    "message": "Found Acme.",
                    "proposals": [
                        {
                            "kind": "source",
                            "source": {
                                "company": "Acme, Inc.",
                                "url": "https://jobs.lever.co/acme",
                            },
                        }
                    ],
                }
            ).proposals[0]
        ],
        session={"proposals": []},
        connectors_path=str(tmp_path / "connectors.yaml"),
        search_path=str(tmp_path / "search.yaml"),
        resolution_cache={
            resolution_cache_key("Acme, Inc.", resolution.requested_url): resolution
        },
        resolve_source=lambda *_args: pytest.fail("source was resolved twice"),
        intelligence_lookup=IntelligenceLookup(),  # type: ignore[arg-type]
    )

    assert proposals[0].source is not None
    assert proposals[0].source.company_intelligence_status == "stale"
    assert proposals[0].source.company_intelligence_version == 4
