from resume_agent.dashboard.selection import all_deletable


def test_all_deletable_requires_nonempty_subset():
    assert all_deletable({1, 2}, {1, 2, 3}) is True
    assert all_deletable({1, 9}, {1, 2, 3}) is False   # 9 not deletable
    assert all_deletable(set(), {1, 2}) is False        # nothing selected
