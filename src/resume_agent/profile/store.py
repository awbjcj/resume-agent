from pathlib import Path

from resume_agent.models.profile import ProfileFacts


def save_facts(facts: ProfileFacts, path: str | Path) -> Path:
    """Write ProfileFacts to an indented JSON file, creating parent dirs."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(facts.model_dump_json(indent=2), encoding="utf-8")
    return p


def load_facts(path: str | Path) -> ProfileFacts:
    """Read ProfileFacts from a JSON file."""
    return ProfileFacts.model_validate_json(Path(path).read_text(encoding="utf-8"))
