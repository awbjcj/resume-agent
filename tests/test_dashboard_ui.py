from resume_agent.dashboard.ui import column_count, fit_block, status_badge


def test_column_count_caps_at_max_on_4k():
    assert column_count(3840) == 4


def test_column_count_scales_with_width():
    assert column_count(1280) == 3   # 1280 // 360 == 3
    assert column_count(800) == 2    # 800 // 360 == 2


def test_column_count_floor_is_one():
    assert column_count(300) == 1
    assert column_count(0) == 1
    assert column_count(-100) == 1


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
