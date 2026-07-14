import re
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import ValidationError

from resume_agent.discovery.scraper.recipe import RECIPE_SCHEMA_VERSION, ScrapeRecipe
from resume_agent.tenancy.context import current_context

RECIPES_DIR = "data/scraper_recipes"

_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]")


def default_recipes_dir() -> Path:
    """Per-tenant recipe cache when a workspace is active, else the flat default.

    Recipes are written and read by the browser scraper inside a pull run, where
    ``RunManager.submit`` has copied the caller's ``UserContext`` into the worker.
    Resolving here keeps every workspace's learned selectors under its own root
    (which provisioning creates and reset targets) instead of a shared cwd path.
    """
    context = current_context()
    return context.paths.scraper_recipes_dir if context is not None else Path(RECIPES_DIR)


def host_key(url: str) -> str:
    """Return a stable, port-free hostname for an absolute board URL."""
    host = urlsplit(url).hostname
    if host is None:
        raise ValueError(f"Scrape target must contain a hostname: {url!r}")
    normalized = host.encode("idna").decode("ascii").lower().rstrip(".")
    return normalized.removeprefix("www.")


def recipe_path(host: str, base_dir: str | Path = RECIPES_DIR) -> Path:
    safe_host = _UNSAFE_FILENAME.sub("_", host)
    return Path(base_dir) / f"{safe_host}.json"


def load_recipe(host: str, base_dir: str | Path = RECIPES_DIR) -> ScrapeRecipe | None:
    path = recipe_path(host, base_dir)
    try:
        recipe = ScrapeRecipe.model_validate_json(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValidationError, ValueError):
        return None
    if recipe.schema_version != RECIPE_SCHEMA_VERSION:
        return None
    return recipe


def save_recipe(
    host: str,
    recipe: ScrapeRecipe,
    base_dir: str | Path = RECIPES_DIR,
) -> None:
    path = recipe_path(host, base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    try:
        temporary.write_text(recipe.model_dump_json(), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
