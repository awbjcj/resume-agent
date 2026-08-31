"""Template ids resolve without trusting CWD or path-like custom stems."""

from pathlib import Path

import pytest

from resume_tailor_harness.render.templates import (
    BUNDLED,
    TemplateNotFoundError,
    list_templates,
    resolve_template,
)
from resume_tailor_harness.render.render_config import RenderConfig
from resume_tailor_harness.services.render_templates import delete_custom_template


def test_classic_is_bundled_and_cwd_independent(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    info = resolve_template("classic")
    assert info.kind == "bundled"
    assert info.path.is_absolute()
    assert info.path.name == "resume.typ"
    assert info.path.exists()
    assert BUNDLED["classic"].title


@pytest.mark.parametrize(
    "template_id",
    ["art-deco", "custom:", "custom:.", "custom:..", "custom:../secret", "custom:a.b"],
)
def test_unknown_or_path_like_ids_raise(template_id) -> None:
    with pytest.raises(TemplateNotFoundError):
        resolve_template(template_id)


def test_custom_resolves_inside_workspace(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    custom = tmp_path / "config" / "templates"
    custom.mkdir(parents=True)
    path = custom / "mine-2.typ"
    path.write_text("hello", encoding="utf-8")
    info = resolve_template("custom:mine-2")
    assert info.id == "custom:mine-2"
    assert info.kind == "custom"
    assert info.path == path


def test_list_templates_is_bundled_then_sorted_custom(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    custom = tmp_path / "config" / "templates"
    custom.mkdir(parents=True)
    for name in ("b.typ", "a.typ", "ignored.txt"):
        (custom / name).write_text("x", encoding="utf-8")
    assert [item.id for item in list_templates()] == [
        "classic",
        "custom:a",
        "custom:b",
    ]


def test_sample_content_matches_current_resume_schema() -> None:
    from resume_tailor_harness.render.sample_content import sample_resume_content

    content = sample_resume_content()
    assert content.contact.name
    assert content.experience[0].bullets
    assert content.education[0].institution
    assert Path(resolve_template("classic").path).exists()


def test_active_template_is_preserved_when_fallback_config_write_fails(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "config" / "templates" / "mine.typ"
    path.parent.mkdir(parents=True)
    path.write_text("template", encoding="utf-8")

    class FailingStore:
        def get(self, _name):
            return RenderConfig(template="custom:mine")

        def put(self, _name, _document):
            raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        delete_custom_template("mine", FailingStore())
    assert path.exists()
