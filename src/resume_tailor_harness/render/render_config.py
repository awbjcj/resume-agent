from pathlib import Path

from resume_tailor_harness.config import load_yaml
from resume_tailor_harness.models.base import ExtensibleModel


class RenderConfig(ExtensibleModel):
    template: str | None = None
    fit_one_page: bool = True
    template_path: str | None = None
    output_dir: str = "output"


def load_render_config(path: str | Path) -> RenderConfig:
    return RenderConfig.model_validate(load_yaml(path))
