from resume_agent.discovery.url_ingest.models import ExtractedJob, PageContent


def test_extracted_job_defaults_to_empty():
    job = ExtractedJob()
    assert job.company is None
    assert job.title is None
    assert job.location is None
    assert job.jd_text == ""


def test_page_content_carries_fetch_metadata():
    page = PageContent(html="<html></html>", final_url="https://x.test", rendered=True)
    assert page.html == "<html></html>"
    assert page.final_url == "https://x.test"
    assert page.rendered is True
