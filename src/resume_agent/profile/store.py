import os
import tempfile
from pathlib import Path

from resume_agent.models.profile import ProfileFacts


def save_facts(facts: ProfileFacts, path: str | Path) -> Path:
    """Atomically write ProfileFacts to an indented JSON file."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(facts.model_dump_json(indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination


def load_facts(path: str | Path) -> ProfileFacts:
    """Read ProfileFacts from a JSON file."""
    return ProfileFacts.model_validate_json(Path(path).read_text(encoding="utf-8"))
