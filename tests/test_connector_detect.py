import resume_agent.discovery.connectors.detect as detect
from resume_agent.discovery.connectors.detect import AtsTarget, detect_ats


def test_l1_greenhouse_url():
    assert detect_ats("https://boards.greenhouse.io/acme") == AtsTarget("greenhouse", "acme")


def test_l1_greenhouse_job_boards_host():
    assert detect_ats("https://job-boards.greenhouse.io/acme/jobs/1") == AtsTarget(
        "greenhouse", "acme"
    )


def test_l1_lever_url():
    assert detect_ats("https://jobs.lever.co/acme") == AtsTarget("lever", "acme")


def test_l1_ashby_url():
    assert detect_ats("https://jobs.ashbyhq.com/acme") == AtsTarget("ashby", "acme")


def test_l1_workday_url():
    target = detect_ats("https://acme.wd1.myworkdayjobs.com/careers")
    assert target is not None and target.ats == "workday"


def test_l1_greenhouse_embed_url_reads_for_param():
    # A directly-configured embed URL keeps the real slug in ?for=, not the path.
    assert detect_ats(
        "https://boards.greenhouse.io/embed/job_board?for=acme"
    ) == AtsTarget("greenhouse", "acme")


def test_l1_greenhouse_embed_url_without_for_falls_through(monkeypatch):
    monkeypatch.setattr(detect, "_get_html", lambda url, client=None: None)
    assert detect_ats("https://boards.greenhouse.io/embed/job_board") is None


def test_l1_does_not_fetch_html(monkeypatch):
    def fail_get_html(url, client=None):
        raise AssertionError("L1 match should not fetch HTML")

    monkeypatch.setattr(detect, "_get_html", fail_get_html)
    assert detect_ats("https://jobs.lever.co/acme") == AtsTarget("lever", "acme")


def test_l2_detects_embedded_greenhouse(monkeypatch):
    html = (
        '<div id="grnhse_app"></div>'
        '<script src="https://boards.greenhouse.io/embed/job_board?for=acme"></script>'
    )
    monkeypatch.setattr(detect, "_get_html", lambda url, client=None: html)
    assert detect_ats("https://careers.acme.com") == AtsTarget("greenhouse", "acme")


def test_l2_detects_embedded_lever(monkeypatch):
    html = '<script src="https://jobs.lever.co/acme/embed"></script>'
    monkeypatch.setattr(detect, "_get_html", lambda url, client=None: html)
    assert detect_ats("https://careers.acme.com") == AtsTarget("lever", "acme")


def test_l2_detects_embedded_ashby(monkeypatch):
    html = '<iframe src="https://jobs.ashbyhq.com/acme"></iframe>'
    monkeypatch.setattr(detect, "_get_html", lambda url, client=None: html)
    assert detect_ats("https://careers.acme.com") == AtsTarget("ashby", "acme")


def test_l2_detects_ashby_board_marker(monkeypatch):
    html = 'window.__ASHBY = {"organizationSlug":"acme"};'
    monkeypatch.setattr(detect, "_get_html", lambda url, client=None: html)
    assert detect_ats("https://careers.acme.com") == AtsTarget("ashby", "acme")


def test_l2_returns_none_for_unknown(monkeypatch):
    monkeypatch.setattr(
        detect,
        "_get_html",
        lambda url, client=None: "<html><body>no ats here</body></html>",
    )
    assert detect_ats("https://careers.acme.com") is None


def test_l2_fails_open_on_fetch_error(monkeypatch):
    monkeypatch.setattr(detect, "_get_html", lambda url, client=None: None)
    assert detect_ats("https://careers.acme.com") is None
