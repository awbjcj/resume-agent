from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.connectors.harvest import harvest_detailed
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
