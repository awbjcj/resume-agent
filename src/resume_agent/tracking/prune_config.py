from pathlib import Path

from resume_agent.config import load_yaml
from resume_agent.models.base import ExtensibleModel


class PruneConfig(ExtensibleModel):
    """Thresholds for auto-prune and the retention sweep (config/prune.yaml)."""

    fit_threshold: int = 40
    stale_days: int = 60
    retention_days: int = 30
    enable_rejected: bool = True
    enable_low_fit: bool = True
    enable_stale: bool = True


def load_prune_config(path: str | Path) -> PruneConfig:
    """Load prune config, returning defaults when the file is absent."""
    if not Path(path).exists():
        return PruneConfig()
    return PruneConfig.model_validate(load_yaml(path))
