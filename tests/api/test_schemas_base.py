from resume_tailor_harness.api.schemas.base import CamelModel, Page, Pagination


class Item(CamelModel):
    fit_score: int
    job_id: int


def test_camel_model_dumps_camelcase_by_alias():
    item = Item(fit_score=87, job_id=3)
    assert item.model_dump(by_alias=True) == {"fitScore": 87, "jobId": 3}


def test_camel_model_accepts_camelcase_input():
    item = Item.model_validate({"fitScore": 5, "jobId": 9})
    assert item.fit_score == 5


def test_camel_model_validates_from_attributes():
    class Dto:
        fit_score = 70
        job_id = 1

    item = Item.model_validate(Dto())
    assert item.fit_score == 70


def test_page_envelope_shape():
    page = Page[Item](
        data=[Item(fit_score=1, job_id=1)],
        pagination=Pagination(page=1, page_size=50, total_items=1, total_pages=1),
    )
    dumped = page.model_dump(by_alias=True)
    assert dumped["pagination"]["pageSize"] == 50
    assert dumped["data"][0]["fitScore"] == 1
