from datetime import datetime, timezone
from pathlib import Path

from resume_tailor_harness.discovery.scraper.models import ScrapedCard
from resume_tailor_harness.discovery.scraper.parser import (
    parse_detail_meta,
    parse_job_detail,
    parse_search_cards,
)

FIXTURES = Path(__file__).parent / "fixtures" / "linkedin"

_DETAIL_HTML = """
<html><body>
  <h1 class="top-card-layout__title">Staff Data Engineer</h1>
  <a class="topcard__org-name-link" href="/company/acme">Acme Corp</a>
  <span class="topcard__flavor--bullet">Berlin, Germany</span>
  <div class="show-more-less-html__markup">Build pipelines.</div>
</body></html>
"""


def test_scraped_card_fields():
    card = ScrapedCard(
        job_id="3700000001",
        title="Senior Backend Engineer",
        company="Acme Corp",
        location="Remote, US",
        url="https://www.linkedin.com/jobs/view/3700000001/",
    )
    assert card.job_id == "3700000001"
    assert card.company == "Acme Corp"


def test_parse_search_cards_extracts_each_posting():
    html = (FIXTURES / "search.html").read_text(encoding="utf-8")
    cards = parse_search_cards(html)
    assert len(cards) == 2

    first = cards[0]
    assert first.job_id == "3700000001"
    assert first.title == "Senior Backend Engineer"
    assert first.company == "Acme Corp"
    assert first.location == "Remote, United States"
    assert first.url == "https://www.linkedin.com/jobs/view/3700000001/"
    assert first.posted_at is None

    second = cards[1]
    assert second.job_id == "3700000002"
    assert second.posted_at is None


def test_parse_search_cards_extracts_absolute_posted_at():
    html = """
    <html><body>
      <div class="base-card" data-entity-urn="urn:li:jobPosting:3700000001">
        <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/3700000001/?trk=public_jobs_jserp-result_search-card"></a>
        <h3 class="base-search-card__title">Senior Backend Engineer</h3>
        <h4 class="base-search-card__subtitle">Acme Corp</h4>
        <span class="job-search-card__location">Remote, United States</span>
        <time class="job-search-card__listdate" datetime="2026-06-01">2 weeks ago</time>
      </div>
    </body></html>
    """
    cards = parse_search_cards(html)
    assert cards[0].posted_at == datetime(2026, 6, 1, tzinfo=timezone.utc)


def test_parse_search_cards_extracts_relative_posted_at():
    now = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)
    html = """
    <html><body>
      <div class="base-card" data-entity-urn="urn:li:jobPosting:3700000001">
        <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/3700000001/?trk=public_jobs_jserp-result_search-card"></a>
        <h3 class="base-search-card__title">Senior Backend Engineer</h3>
        <h4 class="base-search-card__subtitle">Acme Corp</h4>
        <span class="job-search-card__location">Remote, United States</span>
        <time class="job-search-card__listdate">2 days ago</time>
      </div>
    </body></html>
    """
    cards = parse_search_cards(html, now=now)
    assert cards[0].posted_at == datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc)


def test_parse_search_cards_extracts_logged_in_job_card():
    html = """
    <html><body>
      <div class="job-card-container" data-job-id="4427219700">
        <a class="job-card-list__title--link" href="/jobs/view/4427219700/?trk=flagship3_search_srp_jobs">
          Controls Software Development Engineer
        </a>
        <div class="artdeco-entity-lockup__subtitle">FEV North America, Inc.</div>
        <div class="artdeco-entity-lockup__caption">Madison Heights, MI (On-site)</div>
        <time datetime="2026-06-12">5 days ago</time>
      </div>
    </body></html>
    """
    cards = parse_search_cards(html)

    assert cards == [
        ScrapedCard(
            job_id="4427219700",
            title="Controls Software Development Engineer",
            company="FEV North America, Inc.",
            location="Madison Heights, MI (On-site)",
            url="https://www.linkedin.com/jobs/view/4427219700/",
            posted_at=datetime(2026, 6, 12, tzinfo=timezone.utc),
        )
    ]


def test_parse_job_detail_returns_clean_text():
    html = (FIXTURES / "job.html").read_text(encoding="utf-8")
    text = parse_job_detail(html)
    assert "backend engineer" in text.lower()
    assert "5+ years of Python." in text
    assert "Kubernetes" in text
    assert "<li>" not in text


def test_parse_job_detail_returns_empty_when_container_missing():
    # No recognized JD container: must not dump whole-page chrome as the JD.
    html = (
        "<html><body><nav>People also viewed</nav><footer>About</footer></body></html>"
    )
    assert parse_job_detail(html) == ""


def test_parse_job_detail_reads_logged_in_search_panel_container():
    html = """
    <html><body>
      <div class="jobs-box__html-content">
        <h2>About the job</h2>
        <p>Build APIs and automation for internal users.</p>
      </div>
    </body></html>
    """
    text = parse_job_detail(html)
    assert "About the job" in text
    assert "Build APIs and automation" in text


def test_parse_job_detail_reads_logged_in_sdui_container():
    html = """
    <html><body>
      <div componentkey="JobDetails_AboutTheJob_4402958807">
        <div data-sdui-component="com.linkedin.sdui.generated.jobseeker.dsl.impl.aboutTheJob">
          <h2>About the job</h2>
          <p>Maintain high-traffic production services.</p>
        </div>
      </div>
    </body></html>
    """
    text = parse_job_detail(html)
    assert "Maintain high-traffic production services." in text


def test_parse_detail_meta_reads_top_card():
    meta = parse_detail_meta(_DETAIL_HTML)
    assert meta.title == "Staff Data Engineer"
    assert meta.company == "Acme Corp"
    assert meta.location == "Berlin, Germany"


def test_parse_detail_meta_missing_fields_are_none():
    meta = parse_detail_meta("<html><body></body></html>")
    assert meta.title is None
    assert meta.company is None
    assert meta.location is None


def test_parse_detail_meta_reads_logged_in_page_title_fallback():
    # The authenticated flagship3 job-details view has no stable topcard
    # markup (atomic/hashed CSS classes only), but always sets <title> to
    # "{job title} | {company} | LinkedIn".
    html = """
    <html><head><title>Staff Data Engineer | Acme Corp | LinkedIn</title></head>
    <body><div class="_3bc30ca8 _3b42afd3"><p class="e6590096 _91345936">Staff Data Engineer</p></div></body>
    </html>
    """
    meta = parse_detail_meta(html)
    assert meta.title == "Staff Data Engineer"
    assert meta.company == "Acme Corp"
    assert meta.location is None


def test_parse_detail_meta_page_title_with_pipe_in_company_name():
    html = "<html><head><title>SRE | Foo | Bar | LinkedIn</title></head><body></body></html>"
    meta = parse_detail_meta(html)
    assert meta.title == "SRE"
    assert meta.company == "Foo | Bar"


def test_parse_detail_meta_prefers_legacy_topcard_over_page_title():
    html = (
        "<html><head><title>Wrong Title | Wrong Co | LinkedIn</title></head>"
        '<body><h1 class="top-card-layout__title">Staff Data Engineer</h1>'
        '<a class="topcard__org-name-link">Acme Corp</a></body></html>'
    )
    meta = parse_detail_meta(html)
    assert meta.title == "Staff Data Engineer"
    assert meta.company == "Acme Corp"
