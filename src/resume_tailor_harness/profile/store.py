import os
import tempfile
from pathlib import Path

from resume_tailor_harness.models.profile import ProfileFacts


def save_facts(facts: ProfileFacts, path: str | Path) -> Path:
    """Atomically write ProfileFacts to an indented JSON file."""
    from resume_tailor_harness.tenancy.paths import resolve_tenant_path

    destination = resolve_tenant_path(path)
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


_FACTS_CACHE: dict[Path, tuple[int, int, ProfileFacts]] = {}


def load_facts(path: str | Path) -> ProfileFacts:
    """Read ProfileFacts from a JSON file, cached on (mtime_ns, size).

    The returned model is shared across callers — treat it as read-only.
    save_facts() replaces the file atomically, which bumps the key.
    """
    from resume_tailor_harness.tenancy.paths import resolve_tenant_path

    resolved = resolve_tenant_path(path).resolve()
    stat = resolved.stat()
    cached = _FACTS_CACHE.get(resolved)
    if cached is not None and (cached[0], cached[1]) == (
        stat.st_mtime_ns,
        stat.st_size,
    ):
        return cached[2]
    facts = ProfileFacts.model_validate_json(resolved.read_text(encoding="utf-8"))
    _FACTS_CACHE[resolved] = (stat.st_mtime_ns, stat.st_size, facts)
    return facts
