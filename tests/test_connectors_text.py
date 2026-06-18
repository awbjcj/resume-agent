from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.connectors.text import filter_by_search, html_to_text, relevance_gate
from resume_agent.discovery.search_config import SearchConfig


def test_html_to_text_unescapes_and_strips_tags():
    raw = "&lt;p&gt;We use &lt;b&gt;Python&lt;/b&gt; and Kubernetes.&lt;/p&gt;"
    text = html_to_text(raw)
    assert "Python" in text and "Kubernetes" in text
    assert "<" not in text and "&lt;" not in text


def _job(title, jd="some description"):
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


def test_anchor_required_in_title():
    cfg = SearchConfig(role_anchors=["engineer", "ai"])
    out = relevance_gate([_job("AI Applications Engineer"), _job("Creative Lead")], cfg)
    assert [j.title for j in out] == ["AI Applications Engineer"]


def test_exclude_term_rejects_when_anchor_requirement_is_skipped():
    cfg = SearchConfig(exclude_terms=["driver"])
    out = relevance_gate([_job("Class A CDL Driver")], cfg)
    assert out == []


def test_matching_is_case_insensitive():
    cfg = SearchConfig(role_anchors=["ENGINEER"], exclude_terms=["CREATIVE"])
    out = relevance_gate([_job("ai engineer"), _job("Creative Engineer")], cfg)
    assert [j.title for j in out] == ["ai engineer"]


def test_word_boundary_blocks_substring_false_positive():
    cfg = SearchConfig(role_anchors=["rag", "engineer"])
    junk = _job("Warehouse Associate", jd="maintain the garage and storage areas")
    assert relevance_gate([junk], cfg) == []


def test_exclude_matches_title_only_not_body():
    cfg = SearchConfig(role_anchors=["engineer"], exclude_terms=["creative", "sales"])
    keep = _job("AI Engineer", jd="partner with sales; creative problem solving")
    assert [j.title for j in relevance_gate([keep], cfg)] == ["AI Engineer"]


def test_empty_anchors_falls_back_to_legacy_before_excludes():
    cfg = SearchConfig(keywords=["python"], exclude_terms=["driver"])
    out = relevance_gate(
        [
            _job("Backend Developer", jd="we use python daily"),
            _job("Python Driver", jd="we use python daily"),
            _job("Anything", jd="no matching keyword"),
        ],
        cfg,
    )
    assert [j.title for j in out] == ["Backend Developer"]


def test_missing_title_scans_document_for_anchor():
    cfg = SearchConfig(role_anchors=["engineer"])
    out = relevance_gate([_job(None, jd="Senior Engineer wanted")], cfg)
    assert len(out) == 1
