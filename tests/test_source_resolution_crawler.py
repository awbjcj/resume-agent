import httpx

from resume_tailor_harness.discovery.source_resolution.crawler import FirstPartyCrawler
from resume_tailor_harness.security.outbound import PublicTextResponse


def response(url: str, html: str) -> PublicTextResponse:
    return PublicTextResponse(final_url=url, text=html, content_type="text/html")


def test_intuitive_careers_link_produces_strong_smartrecruiters_candidate():
    html = """
    <html><head><title>Careers at Intuitive Surgical</title></head>
    <body><a href="https://careers.smartrecruiters.com/intuitive">Open roles</a></body></html>
    """
    crawler = FirstPartyCrawler(
        fetcher=lambda url: response(url, html), validator=lambda url: None
    )

    report = crawler.crawl("Intuitive Surgical", "https://careers.intuitive.com/en/")

    assert report.first_party_verified is True
    assert report.candidates[0].url == "https://careers.smartrecruiters.com/intuitive"
    assert report.candidates[0].strong_first_party is True


def test_tempus_workday_posting_reduces_to_the_durable_board_root():
    html = """
    <title>Careers at Tempus</title>
    <a href="https://tempus.wd5.myworkdayjobs.com/en-US/Tempus_Careers/job/Engineer_R1">Jobs</a>
    """
    crawler = FirstPartyCrawler(
        fetcher=lambda url: response(url, html), validator=lambda url: None
    )

    report = crawler.crawl("Tempus", "https://www.tempus.com/careers/")

    assert (
        report.candidates[0].url
        == "https://tempus.wd5.myworkdayjobs.com/Tempus_Careers"
    )


def test_crawler_visits_at_most_five_first_party_pages():
    fetched: list[str] = []

    def fetch(url: str) -> PublicTextResponse:
        fetched.append(url)
        links = "".join(
            f'<a href="https://careers.acme.com/jobs/{index}">Career {index}</a>'
            for index in range(10)
        )
        return response(url, f"<title>Acme Careers</title>{links}")

    FirstPartyCrawler(fetcher=fetch, validator=lambda url: None).crawl(
        "Acme", "https://careers.acme.com/jobs"
    )

    assert len(fetched) == 5


def test_crawler_turns_public_http_failures_into_a_safe_resolution_failure():
    request = httpx.Request("GET", "https://careers.acme.example")
    response = httpx.Response(429, request=request)

    def fetch(_url: str) -> PublicTextResponse:
        raise httpx.HTTPStatusError("rate limited", request=request, response=response)

    report = FirstPartyCrawler(fetcher=fetch, validator=lambda _url: None).crawl(
        "Acme", "https://careers.acme.example"
    )

    assert report.error_code == "OFFICIAL_SITE_UNREACHABLE"
