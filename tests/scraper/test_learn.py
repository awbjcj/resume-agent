from datetime import datetime, timezone

import pytest

from resume_agent.discovery.scraper.learn import MAX_LEARN_CHARS, learn_recipe, prune_html
from resume_agent.discovery.scraper.recipe import Pagination, RECIPE_SCHEMA_VERSION, ScrapeRecipe


def _recipe(**overrides):
    values = {
        "learned_at": datetime(2000, 1, 1, tzinfo=timezone.utc),
        "schema_version": 0,
        "card_container": "li.job",
        "jd_container": "div.jd",
        "title_sel": "a",
        "location_sel": None,
        "url_sel": "a",
        "detail_mode": "link",
        "pagination": Pagination(pattern="next", control_sel="a.next"),
    }
    values.update(overrides)
    return ScrapeRecipe(**values)


def test_prune_html_drops_non_content_nodes_and_comments():
    html = """
    <html><head><style>.x { color: red }</style></head><body>
      <!-- ignore me --><script>bad()</script><svg><path /></svg>
      <li class='job'>A</li>
    </body></html>
    """
    pruned = prune_html(html)
    assert "bad()" not in pruned
    assert "color: red" not in pruned
    assert "ignore me" not in pruned
    assert "<svg" not in pruned
    assert "job" in pruned


def test_prune_html_collapses_whitespace_and_truncates():
    pruned = prune_html("<p>one\n\n    two</p>" + "a" * (MAX_LEARN_CHARS * 2))
    assert "one two" in pruned
    assert len(pruned) <= MAX_LEARN_CHARS


class _FakeAgent:
    def __init__(self, content):
        self.content = content

    def run(self, prompt):
        class _Response:
            content: object

        response = _Response()
        response.content = self.content
        return response

    async def arun(self, prompt):
        return self.run(prompt)


def test_learn_recipe_stamps_current_version_and_time():
    recipe = learn_recipe("<li class='job'>A</li>", _FakeAgent(_recipe()))
    assert recipe.schema_version == RECIPE_SCHEMA_VERSION
    assert recipe.learned_at > datetime(2000, 1, 1, tzinfo=timezone.utc)
    assert recipe.card_container == "li.job"


def test_learn_recipe_rejects_unstructured_agent_output():
    with pytest.raises(TypeError, match="Expected ScrapeRecipe"):
        learn_recipe("<li class='job'>A</li>", _FakeAgent("not structured"))
