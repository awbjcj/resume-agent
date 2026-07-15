import resume_agent.discovery.connectors.detect as detect
from resume_agent.discovery.connectors.detect import (
    AtsInspection,
    AtsTarget,
    detect_ats,
    identify_host,
    inspect_ats,
)


def test_l1_greenhouse_url():
    assert detect_ats("https://boards.greenhouse.io/acme") == AtsTarget(
        "greenhouse", "acme"
    )


def test_l1_greenhouse_job_boards_host():
    assert detect_ats("https://job-boards.greenhouse.io/acme/jobs/1") == AtsTarget(
        "greenhouse", "acme"
    )


def test_l1_lever_url():
    assert detect_ats("https://jobs.lever.co/acme") == AtsTarget("lever", "acme")


def test_l1_ashby_url():
    assert detect_ats("https://jobs.ashbyhq.com/acme") == AtsTarget("ashby", "acme")


def test_l1_workday_url():
    assert detect_ats("https://acme.wd1.myworkdayjobs.com/careers") == AtsTarget(
        "workday", tenant="acme", datacenter="wd1", site="careers"
    )


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


def test_inspect_ats_distinguishes_reachable_unknown_from_fetch_failure(monkeypatch):
    monkeypatch.setattr(
        detect,
        "_get_html",
        lambda url, client=None: "<html><body>Careers</body></html>",
    )
    assert inspect_ats("https://careers.acme.com") == AtsInspection(
        target=None, reachable=True
    )

    monkeypatch.setattr(detect, "_get_html", lambda url, client=None: None)
    assert inspect_ats("https://careers.acme.com") == AtsInspection(
        target=None, reachable=False
    )


def test_atstarget_backward_compatible_positional():
    assert AtsTarget("greenhouse", "acme") == AtsTarget("greenhouse", "acme")
    assert AtsTarget("greenhouse", "acme").tenant == ""


def test_atstarget_carries_workday_triple():
    t = AtsTarget(
        "workday", tenant="generalmotors", datacenter="wd5", site="Careers_GM"
    )
    assert (t.tenant, t.datacenter, t.site) == ("generalmotors", "wd5", "Careers_GM")
    assert t.token == ""


def test_atstarget_singleton_needs_only_ats():
    assert AtsTarget("tesla").token == ""


def test_l1_workday_captures_tenant_datacenter_site():
    assert detect_ats(
        "https://generalmotors.wd5.myworkdayjobs.com/Careers_GM"
    ) == AtsTarget(
        "workday", tenant="generalmotors", datacenter="wd5", site="Careers_GM"
    )


def test_l1_workday_site_from_first_path_segment():
    t = detect_ats("https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/jobs")
    assert t == AtsTarget(
        "workday", tenant="nvidia", datacenter="wd5", site="NVIDIAExternalCareerSite"
    )


def test_l1_workday_skips_locale_path_prefix():
    assert detect_ats(
        "https://acme.wd5.myworkdayjobs.com/en-US/Careers/job/R-1"
    ) == AtsTarget("workday", tenant="acme", datacenter="wd5", site="Careers")


def test_l2_workday_requires_full_fetchable_url(monkeypatch):
    html = '<a href="https://acme.wd5.myworkdayjobs.com">Jobs</a>'
    monkeypatch.setattr(detect, "_get_html", lambda url, client=None: html)
    assert detect_ats("https://careers.acme.com") is None


def test_l2_workday_extracts_triple_from_embedded_url(monkeypatch):
    html = '<a href="https://acme.wd5.myworkdayjobs.com/en-US/Careers/job/R-1">Jobs</a>'
    monkeypatch.setattr(detect, "_get_html", lambda url, client=None: html)
    assert detect_ats("https://careers.acme.com") == AtsTarget(
        "workday", tenant="acme", datacenter="wd5", site="Careers"
    )


def test_l2_workday_extracts_site_from_cxs_url(monkeypatch):
    html = '<script>fetch("https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/Careers/jobs")</script>'
    monkeypatch.setattr(detect, "_get_html", lambda url, client=None: html)
    assert detect_ats("https://careers.acme.com") == AtsTarget(
        "workday", tenant="acme", datacenter="wd5", site="Careers"
    )


def test_singleton_tesla_by_host(monkeypatch):
    monkeypatch.setattr(detect, "_get_html", lambda url, client=None: None)
    assert detect_ats(
        "https://www.tesla.com/careers/search/?query=engineer"
    ) == AtsTarget("tesla")


def test_singleton_google_by_host(monkeypatch):
    monkeypatch.setattr(detect, "_get_html", lambda url, client=None: None)
    assert detect_ats("https://careers.google.com/jobs/results/") == AtsTarget("google")


def test_singleton_google_modern_careers_url(monkeypatch):
    monkeypatch.setattr(detect, "_get_html", lambda url, client=None: None)
    url = "https://www.google.com/about/careers/applications/jobs/results"
    assert detect_ats(url) == AtsTarget("google")


def test_singleton_google_www_non_careers_path_not_matched(monkeypatch):
    monkeypatch.setattr(detect, "_get_html", lambda url, client=None: None)
    assert detect_ats("https://www.google.com/search?q=jobs") is None


def test_singleton_precedes_l2(monkeypatch):
    def fail(url, client=None):
        raise AssertionError("singleton match must not fetch HTML")

    monkeypatch.setattr(detect, "_get_html", fail)
    target = detect_ats("https://www.tesla.com/careers")
    assert target is not None
    assert target.ats == "tesla"


def _no_network(monkeypatch):
    def fail(url, client=None):
        raise AssertionError("identify_host must never fetch HTML")

    monkeypatch.setattr(detect, "_get_html", fail)


def test_identify_host_resolves_direct_ats_without_network(monkeypatch):
    _no_network(monkeypatch)
    assert identify_host("https://boards.greenhouse.io/acme/jobs/1") == AtsTarget(
        "greenhouse", "acme"
    )
    assert identify_host("https://acme.wd5.myworkdayjobs.com/Careers") == AtsTarget(
        "workday", tenant="acme", datacenter="wd5", site="Careers"
    )


def test_identify_host_resolves_singleton_without_network(monkeypatch):
    _no_network(monkeypatch)
    assert identify_host("https://www.tesla.com/careers/search") == AtsTarget("tesla")


def test_identify_host_returns_none_for_embedded_careers_page(monkeypatch):
    # No host/path signal -> None, without falling through to the L2 sniff.
    _no_network(monkeypatch)
    assert identify_host("https://careers.acme.com/openings") is None


def test_new_ats_hosts_are_detected_without_network(monkeypatch):
    _no_network(monkeypatch)
    cases = {
        "https://jobs.smartrecruiters.com/Acme/job": AtsTarget(
            "smartrecruiters", "Acme"
        ),
        "https://apply.workable.com/acme/": AtsTarget("workable", "acme"),
        "https://acme.workable.com/": AtsTarget("workable", "acme"),
        "https://acme.recruitee.com/o/engineer": AtsTarget("recruitee", "acme"),
        "https://acme.jobs.personio.de/job/1": AtsTarget(
            "personio", "acme", country="de"
        ),
        "https://acme.breezy.hr/p/1": AtsTarget("breezy", "acme"),
        "https://acme.applytojob.com/apply/jobs": AtsTarget("jazzhr", "acme"),
        "https://acme.bamboohr.com/careers": AtsTarget("bamboohr", "acme"),
    }
    for url, expected in cases.items():
        assert identify_host(url) == expected


def test_workable_job_shortcode_is_not_misidentified_as_account(monkeypatch):
    _no_network(monkeypatch)
    assert identify_host("https://apply.workable.com/j/ABC123") is None
