import json
from datetime import datetime, timezone
from pathlib import Path

from resume_tailor_harness.tenancy.paths import resolve_tenant_path


def read_runs(path: str | Path) -> dict[str, dict]:
    """Return the per-connector run record, or {} if the file does not exist."""
    p = resolve_tenant_path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def record_run(path: str | Path, name: str, added: int, error: str | None) -> None:
    """Upsert one connector's last run."""
    p = resolve_tenant_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    runs = read_runs(p)
    runs[name] = {
        "last_run": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "added": added,
        "error": error,
    }
    p.write_text(json.dumps(runs, indent=2), encoding="utf-8")
