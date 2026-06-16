from resume_agent.dashboard.ui import THEME_CSS, fit_block, meta_line, skill_chip, status_badge
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

    gap_nice = skill_chip(SkillTag("graphql", covered=False, required=False), active=False)
    assert "chip-gap" in gap_nice
    assert "chip-nice" in gap_nice
    assert "+graphql" in gap_nice


def _row(**kw):
    base = dict(
        job_id=1,
        company="C",
        title="T",
        location="L",
        fit_score=80,
        fit_rationale="r",
        sponsorship_signal=None,
        salary_min=None,
        salary_max=None,
        salary_currency="USD",
        remote_policy=None,
        seniority=None,
        employment_type=None,
        industry=None,
        company_size=None,
        posted_at=None,
        skills=[],
    )
    base.update(kw)
    return ShortlistRow(**base)


def test_meta_line_omits_nulls():
    line = meta_line(_row(salary_min=150000, salary_max=190000, seniority="senior"))
    assert "150" in line
    assert "190" in line
    assert "senior" in line.lower()
    assert "None" not in line


def test_meta_line_empty_when_all_null():
    assert meta_line(_row()) == ""


def test_theme_css_has_controldesk_and_chip_classes():
    assert ".controldesk" in THEME_CSS
    assert ".chip-have" in THEME_CSS
    assert ".chip-gap" in THEME_CSS
    assert ".chip-nice" in THEME_CSS
    assert ".chip-sel" in THEME_CSS
