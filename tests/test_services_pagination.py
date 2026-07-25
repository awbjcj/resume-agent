from resume_agent.services.pagination import page_from_slice


def test_page_from_slice_preserves_sql_total_and_second_page_rows():
    page = page_from_slice(["row-3", "row-4"], total=5, page=2, page_size=2)

    assert page.data == ["row-3", "row-4"]
    assert page.page == 2
    assert page.page_size == 2
    assert page.total_items == 5
    assert page.total_pages == 3
