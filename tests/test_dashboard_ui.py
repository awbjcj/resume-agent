from resume_agent.dashboard.ui import THEME_CSS, fit_block, status_badge


def test_theme_css_targets_keyed_cardgrid_containers():
    # The 4K grid binds to st.container(key="cardgrid_…") via its stable
    # st-key class, not the old injected <div class="card-grid"> marker
    # (Streamlit sanitizes that away, so the grid never engaged).
    assert "st-key-cardgrid" in THEME_CSS
    assert "display: grid" in THEME_CSS
    assert ".card-grid +" not in THEME_CSS


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
