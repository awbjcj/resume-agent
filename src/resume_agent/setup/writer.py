import os
from pathlib import Path
from typing import Callable

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
    """Write .env + the five config files, each atomically. Returns per-file status.

    Content is generated lazily per file so a generator failure (e.g. a missing
    ``.example`` scaffold) degrades to a per-file ``"error: ..."`` status rather
    than crashing the whole write.
    """
    root = Path(root)
    builders: dict[Path, Callable[[], str]] = {
        root / ".env": lambda: _env_content(state, root),
        root / "config" / "profile_sources.yaml": lambda: build_profile_sources(state),
        root / "config" / "search.yaml": lambda: build_search(state),
        root / "config" / "connectors.yaml": lambda: build_connectors(state),
        root / "config" / "review.yaml": lambda: render_from_example(root / "config" / "review.yaml.example"),
        root / "config" / "render.yaml": lambda: render_from_example(root / "config" / "render.yaml.example"),
    }
    report: dict[str, str] = {}
    for path, build in builders.items():
        try:
            content = build()
        except OSError as exc:
            report[str(path)] = f"error: {exc}"
            continue
        report[str(path)] = _atomic_write(path, content)
    return report


def load_existing_state(root: str | Path = ".") -> WizardState:
    """Pre-fill a WizardState from any config that already exists (re-run safety).

    Best-effort and per-section guarded: a missing, malformed, or wrong-schema
    file leaves that section at its defaults rather than raising. This runs in
    the SetupApp constructor, and the wizard is the tool you reach for *because*
    config is broken — so it must still launch on a corrupt config.
    """
    root = Path(root)
    state = WizardState()

    env_path = root / ".env"
    if env_path.exists():
        try:
            env = parse_env(env_path.read_text(encoding="utf-8"))
            state.anthropic_api_key = env.get("ANTHROPIC_API_KEY", "")
            state.github_token = env.get("GITHUB_TOKEN", "")
            state.adzuna_app_id = env.get("ADZUNA_APP_ID", "")
            state.adzuna_app_key = env.get("ADZUNA_APP_KEY", "")
            state.linkedin_email = env.get("LINKEDIN_EMAIL", "")
            state.linkedin_password = env.get("LINKEDIN_PASSWORD", "")
            state.db_url = env.get("DB_URL", state.db_url)
            # managed_env writes these, so restore them too or a re-run reverts
            # any customized model to the WizardState default.
            state.cheap_model = env.get("CHEAP_MODEL", state.cheap_model)
            state.mid_model = env.get("MID_MODEL", state.mid_model)
            state.premium_model = env.get("PREMIUM_MODEL", state.premium_model)
        except Exception:  # noqa: BLE001 — best-effort pre-fill; bad .env -> defaults
            pass

    sources = root / "config" / "profile_sources.yaml"
    if sources.exists():
        try:
            data = load_yaml(sources) or {}
            state.resume_path = data.get("resume_path", "")
            state.github_username = data.get("github_username", "")
        except Exception:  # noqa: BLE001 — best-effort pre-fill; bad file -> defaults
            pass

    search = root / "config" / "search.yaml"
    if search.exists():
        try:
            cfg = load_search_config(search)
            state.keywords = cfg.keywords
            state.titles = cfg.titles
            state.locations = cfg.locations
            state.remote_policy = cfg.remote_policy or "any"
            state.min_salary = cfg.min_salary
            state.yoe_min = cfg.yoe_min
            state.yoe_max = cfg.yoe_max
            state.sponsorship_required = cfg.sponsorship_required
        except Exception:  # noqa: BLE001 — best-effort pre-fill; bad file -> defaults
            pass

    connectors = root / "config" / "connectors.yaml"
    if connectors.exists():
        try:
            cfg = load_connectors_config(connectors)
            state.greenhouse_enabled = cfg.greenhouse.enabled
            state.greenhouse_boards = [
                {"token": b.token, "company": b.company or b.token} for b in cfg.greenhouse.boards
            ]
            state.adzuna_enabled = cfg.adzuna.enabled
            state.adzuna_country = cfg.adzuna.country
            state.remoteok_enabled = cfg.remoteok.enabled
            state.linkedin_enabled = cfg.linkedin.enabled
        except Exception:  # noqa: BLE001 — best-effort pre-fill; bad file -> defaults
            pass

    return state
