from pathlib import Path

from resume_agent.config import load_yaml
from resume_agent.models.base import ExtensibleModel


class RenderConfig(ExtensibleModel):
    template_path: str = "templates/resume.typ"
    output_dir: str = "output"


def load_render_config(path: str | Path) -> RenderConfig:
    return RenderConfig.model_validate(load_yaml(path))
