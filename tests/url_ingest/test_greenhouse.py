from resume_agent.discovery.url_ingest.greenhouse import parse_greenhouse

_HTML = """
<html><body>
  <h1 class="app-title">Senior Platform Engineer</h1>
  <span class="company-name">at Globex</span>
  <div class="location">Remote - US</div>
  <div id="content">
    <p>You will own our deploy tooling.</p>
    <p>Requirements: 5 years of Go.</p>
  </div>
</body></html>
"""


def test_parse_greenhouse_extracts_all_fields():
    job = parse_greenhouse(_HTML)
    assert job.title == "Senior Platform Engineer"
    assert job.company == "Globex"
    assert job.location == "Remote - US"
    assert "deploy tooling" in job.jd_text
    assert "5 years of Go" in job.jd_text


def test_parse_greenhouse_missing_content_yields_empty_jd():
    job = parse_greenhouse("<html><body></body></html>")
    assert job.jd_text == ""
    assert job.company is None
