import json
from datetime import timezone
from pathlib import Path
from typing import Any

import pytest

import resume_agent.discovery.connectors.google as google
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.search_config import SearchConfig

TARGET = AtsTarget("google")
FIXTURE = (Path(__file__).parent / "fixtures" / "google" / "results.html").read_text(
    encoding="utf-8"
)


def _row(
    job_id="123",
    title="Software Engineer",
    location="Austin, TX, USA",
    about="<p>About the team.</p>",
    qualifications="<p>Python required.</p>",
    responsibilities="<p>Build systems.</p>",
    posted=1782808699,
) -> list[Any]:
    row: list[Any] = [None] * 21
    row[0] = job_id
    row[1] = title
    row[2] = "https://www.google.com/about/careers/applications/signin?jobId=x"
    row[3] = [None, responsibilities]
    row[4] = [None, qualifications]
    row[7] = "Google"
    row[9] = [[location, ["street address"], "City", "ST"]]
    row[10] = [None, about]
    row[12] = [posted, 0]
    return row


def _page_html(rows: list[object]) -> str:
    payload = json.dumps([rows, None, len(rows), 20])
    return (
        "<script>AF_initDataCallback({key: 'ds:1', hash: '2', data:"
        + payload
        + ", sideChannel: {}});</script>"
    )


def test_extract_job_rows_reads_live_shaped_fixture():
    rows = google.extract_job_rows(FIXTURE)
    assert [row[1] for row in rows] == [
        "Software Engineer",
        "Site Reliability Engineer",
    ]


def test_extract_job_rows_accepts_valid_empty_jobs_blob():
    assert google.extract_job_rows(_page_html([])) == []


@pytest.mark.parametrize(
    "html",
    [
        "<html><body>no callback</body></html>",
        "<script>AF_initDataCallback({key: 'ds:1', data:[broken], sideChannel: {}});</script>",
        "<script>AF_initDataCallback({key: 'ds:1', data:[[]], sideChannel: {}});</script>",
    ],
)
def test_extract_job_rows_raises_when_jobs_blob_drifted(html):
    with pytest.raises(ValueError, match="Google jobs blob"):
        google.extract_job_rows(html)


def test_parse_job_rows_maps_fields():
    job = google.parse_job_rows([_row()])[0]
    assert job.source == "google"
    assert job.company == "Google"
    assert job.title == "Software Engineer"
    assert job.location == "Austin, TX, USA"
    assert job.url == (
        "https://www.google.com/about/careers/applications/jobs/results/123"
    )
    assert "About the team." in job.jd_text
    assert "Python required." in job.jd_text
    assert "Build systems." in job.jd_text
    assert job.posted_at is not None
    assert job.posted_at.tzinfo == timezone.utc


def test_parse_job_rows_keeps_every_google_location():
    row = _row(location="Austin, TX, USA")
    row[9].extend(
        [
            ["New York, NY, USA", [], "New York", None, "NY", "US"],
            ["Austin, TX, USA", [], "Austin", None, "TX", "US"],
        ]
    )

    job = google.parse_job_rows([row])[0]

    assert job.location == "Austin, TX, USA | New York, NY, USA"


def test_parse_job_rows_strips_material_icon_tokens():
    job = google.parse_job_rows(
        [_row(about="<p>Google _corporate_fare_ Google _place_ Austin</p>")]
    )[0]
    assert "corporate_fare" not in job.jd_text
    assert "_place_" not in job.jd_text


def test_parse_job_rows_skips_malformed_rows():
    good = _row()
    jobs = google.parse_job_rows([["", None], "not-a-row", good, [None]])
    assert [job.title for job in jobs] == ["Software Engineer"]


def test_fetch_google_pages_until_valid_empty_blob(monkeypatch):
    calls = []

    class _Resp:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            pass

    def fake_get(
        url: str,
        params: dict[str, object],
        headers: dict[str, str] | None = None,
        **kwargs: object,
    ) -> _Resp:
        calls.append(dict(params))
        return _Resp(FIXTURE if params["page"] == 1 else _page_html([]))

    monkeypatch.setattr(google.board, "get", fake_get)
    jobs = google.fetch_google(TARGET, SearchConfig())
    assert [job.title for job in jobs] == [
        "Software Engineer",
        "Site Reliability Engineer",
    ]
    assert calls[0]["q"] == ""
    assert [call["page"] for call in calls] == [1, 2]


def test_fetch_google_limit_counts_relevant_unseen_rows(monkeypatch):
    calls = []

    class _Resp:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            pass

    def fake_get(
        url: str,
        params: dict[str, object],
        headers: dict[str, str] | None = None,
        **kwargs: object,
    ) -> _Resp:
        calls.append(params["page"])
        if params["page"] == 1:
            return _Resp(
                _page_html(
                    [
                        _row(job_id="driver", title="CDL Driver"),
                        _row(job_id="seen", title="Software Engineer"),
                    ]
                )
            )
        return _Resp(_page_html([_row(job_id="fresh", title="Platform Engineer")]))

    monkeypatch.setattr(google.board, "get", fake_get)
    jobs = google.fetch_google(
        TARGET,
        SearchConfig(role_anchors=["Engineer"]),
        limit=1,
        skip_seen=lambda job: job.url is not None and job.url.endswith("/seen"),
    )
    assert [job.title for job in jobs] == ["Platform Engineer"]
    assert calls == [1, 2]
