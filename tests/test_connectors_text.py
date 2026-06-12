from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.connectors.text import filter_by_search, html_to_text
from resume_agent.discovery.search_config import SearchConfig


def test_html_to_text_unescapes_and_strips_tags():
    raw = "&lt;p&gt;We use &lt;b&gt;Python&lt;/b&gt; and Kubernetes.&lt;/p&gt;"
    text = html_to_text(raw)
    assert "Python" in text and "Kubernetes" in text
    assert "<" not in text and "&lt;" not in text


def _job(title, jd):
    return RawJob("greenhouse", None, "Acme", title, "Remote", jd)


def test_filter_keeps_all_when_no_keywords():
    jobs = [_job("Chef", "cooking")]
    assert filter_by_search(jobs, SearchConfig()) == jobs


def test_filter_matches_keyword_in_title_or_jd_case_insensitively():
    jobs = [
        _job("Backend Engineer", "build services"),
        _job("Chef", "make pasta"),
        _job("Designer", "We use PYTHON daily"),
    ]
    cfg = SearchConfig(keywords=[" python "], titles=["engineer"])
    kept = {j.title for j in filter_by_search(jobs, cfg)}
    assert kept == {"Backend Engineer", "Designer"}
