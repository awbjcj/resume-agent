from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.connectors.harvest import gate_and_limit, harvest_detailed
from resume_agent.discovery.search_config import SearchConfig


def _row(url):
    return RawJob("workday", url, "Acme", "Backend Engineer", "Remote", "")


def test_harvest_detailed_skips_known_before_detail_fetch():
    fetched = []

    def fetch_detail(row):
        fetched.append(row.url)
        return {"description": "Build backend systems"}

    def apply_detail(row, detail):
        row.jd_text = detail["description"]

    jobs = harvest_detailed(
        [_row("https://wd/1"), _row("https://wd/2")],
        fetch_detail,
        apply_detail,
        search=SearchConfig(),
        limit=None,
        skip_seen=lambda row: row.url == "https://wd/1",
    )

    assert fetched == ["https://wd/2"]
    assert [job.url for job in jobs] == ["https://wd/2"]


def test_harvest_detailed_isolates_apply_detail_error():
    # A malformed detail (e.g. a page missing its JobPosting JSON-LD) makes
    # apply_detail raise; that row is skipped, never the whole batch.
    def fetch_detail(row):
        return {"html": "<html></html>"}

    def apply_detail(row, detail):
        if row.url.endswith("/1"):
            raise ValueError("detail did not contain JobPosting JSON-LD")
        row.jd_text = "Build backend systems"

    jobs = harvest_detailed(
        [_row("https://wd/1"), _row("https://wd/2")],
        fetch_detail,
        apply_detail,
        search=SearchConfig(),
        limit=None,
    )

    assert [job.url for job in jobs] == ["https://wd/2"]


def test_gate_and_limit_drops_skip_seen_before_limit():
    # skip_seen runs after the gate and before the cap, so the limit fills with
    # unseen rows rather than truncating first and then dropping a known one.
    jobs = [_row("https://wd/1"), _row("https://wd/2"), _row("https://wd/3")]

    kept, filtered = gate_and_limit(
        jobs,
        SearchConfig(),
        limit=2,
        skip_seen=lambda row: row.url == "https://wd/1",
    )

    assert [job.url for job in kept] == ["https://wd/2", "https://wd/3"]
    assert filtered == 0
