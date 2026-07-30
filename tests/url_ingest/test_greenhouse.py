from resume_agent.discovery.url_ingest.greenhouse import read_greenhouse_posting

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


_MODERN_HTML = """
<html><body>
  <h1 class="section-header">Staff Data Engineer</h1>
  <div class="job__location"><div>New York, NY</div></div>
  <div class="job__description">
    <p>You will own the warehouse.</p>
    <p>Requirements: 5 years of SQL.</p>
  </div>
</body></html>
"""


def test_read_greenhouse_posting_extracts_all_fields():
    job = read_greenhouse_posting(_HTML)
    assert job is not None
    assert job.title == "Senior Platform Engineer"
    assert job.company == "Globex"
    assert job.location == "Remote - US"
    assert "deploy tooling" in job.jd_text
    assert "5 years of Go" in job.jd_text


def test_read_greenhouse_posting_reads_modern_job_boards_layout():
    # job-boards.greenhouse.io (which detect.py also routes here) renames every
    # class the legacy boards.greenhouse.io layout used.
    job = read_greenhouse_posting(_MODERN_HTML)
    assert job is not None
    assert job.title == "Staff Data Engineer"
    assert job.location == "New York, NY"
    assert "own the warehouse" in job.jd_text
    assert "5 years of SQL" in job.jd_text


def test_read_greenhouse_posting_missing_content_returns_none():
    # None (not an ExtractedJob with an empty jd_text) is what lets the caller
    # fall through to its next source instead of accepting an empty read.
    assert read_greenhouse_posting("<html><body></body></html>") is None
