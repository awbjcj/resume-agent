import os
from pathlib import Path

from resume_agent.config import load_yaml
from resume_agent.discovery.connectors.config import load_connectors_config
from resume_agent.discovery.search_config import load_search_config
from resume_agent.setup.env_writer import format_env, merge_env, parse_env
from resume_agent.setup.state import WizardState
from resume_agent.setup.yaml_gen import (
    build_connectors,
    build_profile_sources,
    build_search,
    render_from_example,
)


def _atomic_write(path: Path, content: str) -> str:
    """Write ``content`` to ``path`` atomically. Returns 'written' or 'error: ...'."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
        return "written"
    except OSError as exc:
        if tmp.exists():
            tmp.unlink()
        return f"error: {exc}"


def _env_content(state: WizardState, root: Path) -> str:
    env_path = root / ".env"
    existing = parse_env(env_path.read_text(encoding="utf-8")) if env_path.exists() else {}
    return format_env(merge_env(existing, state.managed_env()))


def atomic_write_all(state: WizardState, root: str | Path = ".") -> dict[str, str]:
    """Write .env + the five config files, each atomically. Returns per-file status."""
    root = Path(root)
    plan: dict[Path, str] = {
        root / ".env": _env_content(state, root),
        root / "config" / "profile_sources.yaml": build_profile_sources(state),
        root / "config" / "search.yaml": build_search(state),
        root / "config" / "connectors.yaml": build_connectors(state),
        root / "config" / "review.yaml": render_from_example(root / "config" / "review.yaml.example"),
        root / "config" / "render.yaml": render_from_example(root / "config" / "render.yaml.example"),
    }
    return {str(path): _atomic_write(path, content) for path, content in plan.items()}


def load_existing_state(root: str | Path = ".") -> WizardState:
    """Pre-fill a WizardState from any config that already exists (re-run safety)."""
    root = Path(root)
    state = WizardState()

    env_path = root / ".env"
    if env_path.exists():
        env = parse_env(env_path.read_text(encoding="utf-8"))
        state.anthropic_api_key = env.get("ANTHROPIC_API_KEY", "")
        state.github_token = env.get("GITHUB_TOKEN", "")
        state.adzuna_app_id = env.get("ADZUNA_APP_ID", "")
        state.adzuna_app_key = env.get("ADZUNA_APP_KEY", "")
        state.linkedin_email = env.get("LINKEDIN_EMAIL", "")
        state.linkedin_password = env.get("LINKEDIN_PASSWORD", "")
        state.db_url = env.get("DB_URL", state.db_url)

    sources = root / "config" / "profile_sources.yaml"
    if sources.exists():
        data = load_yaml(sources)
        state.resume_path = data.get("resume_path", "")
        state.github_username = data.get("github_username", "")

    search = root / "config" / "search.yaml"
    if search.exists():
        cfg = load_search_config(search)
        state.keywords = cfg.keywords
        state.titles = cfg.titles
        state.locations = cfg.locations
        state.remote_policy = cfg.remote_policy or "any"
        state.min_salary = cfg.min_salary
        state.yoe_min = cfg.yoe_min
        state.yoe_max = cfg.yoe_max
        state.sponsorship_required = cfg.sponsorship_required

    connectors = root / "config" / "connectors.yaml"
    if connectors.exists():
        cfg = load_connectors_config(connectors)
        state.greenhouse_enabled = cfg.greenhouse.enabled
        state.greenhouse_boards = [
            {"token": b.token, "company": b.company or b.token} for b in cfg.greenhouse.boards
        ]
        state.adzuna_enabled = cfg.adzuna.enabled
        state.adzuna_country = cfg.adzuna.country
        state.remoteok_enabled = cfg.remoteok.enabled
        state.linkedin_enabled = cfg.linkedin.enabled

    return state
