from resume_agent.dashboard.ui import column_count


def test_column_count_caps_at_max_on_4k():
    assert column_count(3840) == 4


def test_column_count_scales_with_width():
    assert column_count(1280) == 3   # 1280 // 360 == 3
    assert column_count(800) == 2    # 800 // 360 == 2


def test_column_count_floor_is_one():
    assert column_count(300) == 1
    assert column_count(0) == 1
    assert column_count(-100) == 1
