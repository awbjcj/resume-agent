import resume_agent.discovery.connectors.google as google
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.search_config import SearchConfig

TARGET = AtsTarget("google")
PAGE = {"count": 1, "jobs": [{
    "title": "Software Engineer",
    "locations": [{"display": "Mountain View, CA"}],
    "description": "<p>Build with Go.</p>",
    "apply_url": "https://careers.google.com/jobs/results/1/",
    "publish_date": "2026-06-01",
}]}


def test_parse_google_jobs():
    jobs = google.parse_jobs(PAGE)
    j = jobs[0]
    assert j.source == "google"
    assert j.company == "Google"
    assert j.title == "Software Engineer"
    assert j.location == "Mountain View, CA"
    assert "Go" in j.jd_text
    assert j.url == "https://careers.google.com/jobs/results/1/"


def test_parse_google_jobs_removes_material_icon_tokens():
    page = {
        "jobs": [
            {
                "title": "Forward Deployed Engineer",
                "locations": [{"display": "San Francisco, CA"}],
                "description": (
                    "<p>Google _corporate_fare_ Google _place_ San Francisco, CA "
                    "_laptop_windows_ Remote eligible **Mid**</p>"
                    "<p>Build applied AI systems.</p>"
                ),
                "apply_url": "https://careers.google.com/jobs/results/2/",
            }
        ]
    }

    job = google.parse_jobs(page)[0]

    assert "corporate_fare" not in job.jd_text
    assert "_place_" not in job.jd_text
    assert "laptop_windows" not in job.jd_text
    assert "\\*\\*" not in job.jd_text
    assert "Remote eligible Mid" in job.jd_text
    assert "Build applied AI systems." in job.jd_text


def test_fetch_google_is_search_shaped(monkeypatch):
    sent = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return PAGE if sent.setdefault("page", 0) == 0 else {"jobs": []}

    def fake_get(url, params, timeout):
        sent["q"] = params.get("q")
        sent["page"] = sent.get("page", -1) + 1
        return _Resp()

    monkeypatch.setattr(google.httpx, "get", fake_get)
    jobs = google.fetch_google(TARGET, SearchConfig(titles=["Software Engineer"]))
    assert sent["q"] == "Software Engineer"
    assert [j.title for j in jobs] == ["Software Engineer"]
