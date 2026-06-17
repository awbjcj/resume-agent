from datetime import datetime

from resume_agent.dashboard.ui import (
    THEME_CSS,
    clamp_text,
    fit_block,
    meta_line,
    skill_chip,
    skill_strip,
    status_badge,
)
from resume_agent.tracking.queries import ShortlistRow, SkillTag


def test_theme_css_targets_keyed_cardgrid_containers():
    # The 4K grid binds to st.container(key="cardgrid_…") via its stable
    # st-key class, not the old injected <div class="card-grid"> marker
    # (Streamlit sanitizes that away, so the grid never engaged).
    assert "st-key-cardgrid" in THEME_CSS
    assert "display: grid" in THEME_CSS
    assert ".card-grid +" not in THEME_CSS
    # In Streamlit ≥1.39 the st-key class sits on the SAME node as the
    # stVerticalBlock testid, so the grid is the keyed element itself; a child
    # combinator would match nothing. Shortlist (scannable summary cards) and
    # pipeline (full-width detail cards with expandable JDs) get distinct grids.
    assert (
        'div[data-testid="stVerticalBlock"][class*="st-key-cardgrid_shortlist"]'
        in THEME_CSS
    )
    assert (
        'div[data-testid="stVerticalBlock"][class*="st-key-cardgrid_pipeline"]'
        in THEME_CSS
    )
    # stVerticalBlockBorderWrapper does not exist in current Streamlit; card
    # styling must not be hung off that (nonexistent) testid selector.
    assert '[data-testid="stVerticalBlockBorderWrapper"]' not in THEME_CSS


def test_status_badge_returns_html_for_known_status():
    html = status_badge("offered")
    assert "offered" in html.lower()
    assert "span" in html.lower()


def test_fit_block_colors_by_threshold():
    assert "—" in fit_block(None)            # no score → em dash
    high = fit_block(88)
    assert "88" in high
    assert 'role="meter"' in high
    assert 'aria-valuenow="88"' in high


def test_skill_chip_encodes_coverage_requirement_and_active():
    covered_must = skill_chip(SkillTag("python", covered=True, required=True), active=True)
    assert "python" in covered_must
    assert "chip-have" in covered_must
    assert "chip-sel" in covered_must
    assert "chip-text" in covered_must
    assert 'title="python"' in covered_must

    gap_nice = skill_chip(SkillTag("graphql", covered=False, required=False), active=False)
    assert "chip-gap" in gap_nice
    assert "chip-nice" in gap_nice
    assert "+graphql" in gap_nice


def _row(
    *,
    job_id: int = 1,
    company: str | None = "C",
    title: str | None = "T",
    location: str | None = "L",
    fit_score: int | None = 80,
    fit_rationale: str | None = "r",
    sponsorship_signal: str | None = None,
    salary_min: int | None = None,
    salary_max: int | None = None,
    salary_currency: str | None = "USD",
    remote_policy: str | None = None,
    seniority: str | None = None,
    employment_type: str | None = None,
    industry: str | None = None,
    company_size: str | None = None,
    posted_at: datetime | None = None,
    skills: list[SkillTag] | None = None,
) -> ShortlistRow:
    return ShortlistRow(
        job_id=job_id,
        company=company,
        title=title,
        location=location,
        fit_score=fit_score,
        fit_rationale=fit_rationale,
        sponsorship_signal=sponsorship_signal,
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=salary_currency,
        remote_policy=remote_policy,
        seniority=seniority,
        employment_type=employment_type,
        industry=industry,
        company_size=company_size,
        posted_at=posted_at,
        skills=skills or [],
    )


def test_meta_line_omits_nulls():
    line = meta_line(_row(salary_min=150000, salary_max=190000, seniority="senior"))
    assert "150" in line
    assert "190" in line
    assert "senior" in line.lower()
    assert "None" not in line


def test_meta_line_empty_when_all_null():
    assert meta_line(_row()) == ""


def test_theme_css_styles_keyed_controldesk_container():
    # The filter panel must bind to st.container(key="controldesk") via its
    # stable st-key class. A bare <div class="controldesk"> marker gets
    # sanitized into an empty box (the same trap the card grids avoid), so the
    # panel styling hangs off the keyed container, not a plain class.
    assert 'class*="st-key-controldesk"' in THEME_CSS
    assert ".controldesk-head" in THEME_CSS
    assert ".chip-have" in THEME_CSS
    assert ".chip-gap" in THEME_CSS
    assert ".chip-nice" in THEME_CSS
    assert ".chip-sel" in THEME_CSS
    assert ".skills-clip .chip" in THEME_CSS
    assert "grid-template-columns: minmax(0, 1fr) auto" in THEME_CSS
    assert 'div[data-testid="stElementContainer"]:has(.controldesk-head)' in THEME_CSS
    assert "margin-bottom: 0.55rem" in THEME_CSS
    assert '+ div[data-testid="stLayoutWrapper"]' in THEME_CSS
    assert "padding-top: 0.55rem" in THEME_CSS


def test_clamp_text_plain_when_short_and_details_when_long():
    short = clamp_text("brief reason")
    assert "<details" not in short
    assert "brief reason" in short

    long = clamp_text("word " * 60, lines=2)
    assert "<details" in long
    assert "xt-clamp" in long
    assert 'style="--xt-lines:2"' in long


def test_clamp_text_word_preview_keeps_full_text_expandable():
    text = " ".join(f"word{i}" for i in range(12))
    out = clamp_text(text, preview_words=5)
    assert "<details" in out
    assert "xt-excerpt" in out
    assert "xt-full" in out
    assert "word4..." in out
    assert "word11" in out

    short = clamp_text("one two three", preview_words=5)
    assert "<details" not in short
    assert "one two three" in short


def test_clamp_text_escapes_html():
    out = clamp_text("<script>alert(1)</script> " + "x" * 100)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_skill_strip_plain_under_head_and_toggle_over_head():
    plain = skill_strip(["<a>", "<b>", "<c>"])
    assert "<details" not in plain
    assert plain == '<div class="skills"><a><b><c></div>'

    many = skill_strip([f"<c{i}>" for i in range(8)])
    assert "xt-skills" in many
    # 8 chips, head=6 -> exactly 2 hidden, surfaced as the +N count.
    assert 'data-n="2"' in many
    assert "skills-rest" in many
