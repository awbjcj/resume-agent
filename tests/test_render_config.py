from pathlib import Path

from resume_tailor_harness.render.render_config import RenderConfig, load_render_config
from resume_tailor_harness.render.templates import template_path_for


def test_defaults():
    cfg = RenderConfig()
    assert cfg.template is None
    assert cfg.template_path is None
    assert cfg.output_dir == "output"
    assert cfg.fit_one_page is True
    assert template_path_for(cfg).name == "resume.typ"


def test_load_from_yaml(tmp_path):
    f = tmp_path / "render.yaml"
    f.write_text(
        "template_path: templates/custom.typ\noutput_dir: build/pdfs\n",
        encoding="utf-8",
    )
    cfg = load_render_config(f)
    assert cfg.template_path == "templates/custom.typ"
    assert cfg.output_dir == "build/pdfs"


def test_new_template_keys_and_precedence(tmp_path):
    path = tmp_path / "render.yaml"
    path.write_text(
        "template: classic\nfit_one_page: false\ntemplate_path: ignored.typ\n",
        encoding="utf-8",
    )
    config = load_render_config(path)
    assert config.template == "classic"
    assert config.fit_one_page is False
    assert template_path_for(config).name == "resume.typ"


def test_legacy_template_path_is_preserved(tmp_path):
    config = RenderConfig(template_path="local/custom.typ")
    assert template_path_for(config) == Path("local/custom.typ")


def test_classic_compiles_with_pinned_root(tmp_path):
    from resume_tailor_harness.render.renderer import render_pdf
    from resume_tailor_harness.render.sample_content import sample_resume_content

    output = render_pdf(
        sample_resume_content(),
        tmp_path / "sample.pdf",
        template_path_for(RenderConfig()),
        fit_pages=None,
    )
    assert output.exists()
    assert output.stat().st_size > 0
