from resume_agent.render.render_config import RenderConfig, load_render_config


def test_defaults():
    cfg = RenderConfig()
    assert cfg.template_path == "templates/resume.typ"
    assert cfg.output_dir == "output"


def test_load_from_yaml(tmp_path):
    f = tmp_path / "render.yaml"
    f.write_text(
        "template_path: templates/custom.typ\noutput_dir: build/pdfs\n", encoding="utf-8"
    )
    cfg = load_render_config(f)
    assert cfg.template_path == "templates/custom.typ"
    assert cfg.output_dir == "build/pdfs"
