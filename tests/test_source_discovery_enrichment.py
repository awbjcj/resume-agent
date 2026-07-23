from resume_agent.discovery.scout_models import Citation
from resume_agent.discovery.source_scout import ScoutCandidate
from resume_agent.services import source_discovery as svc
from resume_agent.services.sources import SourcePreview

from test_source_discovery import run_worker


def test_url_less_avoid_skips_probe_and_keeps_safe_evidence(monkeypatch, tmp_path):
    def unexpected_probe(*_args, **_kwargs):
        raise AssertionError("avoid rows must not be probed")

    monkeypatch.setattr(svc, "preview_source", unexpected_probe)
    candidate = ScoutCandidate(
        company="RiskCo",
        signal="avoid",
        fit_score=10,
        reason="Hiring freeze",
        citations=[
            Citation(url="https://news.example/risk", title="Hiring freeze"),
            Citation(url="javascript:alert(1)", title="unsafe"),
        ],
    )

    result = run_worker(monkeypatch, tmp_path, [candidate], {})

    assert result["candidates"] == [
        {
            "company": "RiskCo",
            "url": "",
            "reason": "Hiring freeze",
            "confidence": "medium",
            "status": "avoid",
            "signal": "avoid",
            "fitScore": 10,
            "citations": [
                {"url": "https://news.example/risk", "title": "Hiring freeze"}
            ],
            "ats": None,
            "token": None,
            "roleCount": None,
            "error": None,
            "errorCode": None,
        }
    ]


def test_source_rows_rank_by_status_then_score_stably(monkeypatch, tmp_path):
    candidates = [
        ScoutCandidate(company="Unscored", careers_url="https://u.example", fit_score=None),
        ScoutCandidate(company="High", careers_url="https://h.example", fit_score=90),
        ScoutCandidate(company="Tie first", careers_url="https://t1.example", fit_score=70),
        ScoutCandidate(company="Tie second", careers_url="https://t2.example", fit_score=70),
    ]
    previews = {
        row.careers_url: SourcePreview(ok=True, url=row.careers_url) for row in candidates
    }

    result = run_worker(monkeypatch, tmp_path, candidates, previews)

    assert [row["company"] for row in result["candidates"]] == [
        "High",
        "Tie first",
        "Tie second",
        "Unscored",
    ]
