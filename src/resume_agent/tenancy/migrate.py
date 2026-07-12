from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

ADOPTION_JOURNAL = ".tenancy-adoption.json"
_LEGACY_CHILDREN = (
    "resume_agent.db",
    "resume_agent.db-wal",
    "resume_agent.db-shm",
    "profile",
    "config",
    "output",
    "runs",
    "progress",
    "scraper_recipes",
    "workday_facets",
    "taxonomy",
)


class AdoptionError(RuntimeError):
    pass


def is_legacy_root(data_root: Path | str) -> bool:
    root = Path(data_root)
    return (
        any((root / child).exists() for child in _LEGACY_CHILDREN)
        or (root / ".env").is_file()
    )


def _write_journal(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def adopt_legacy_root(data_root: Path | str, admin_id: str) -> list[str]:
    root = Path(data_root)
    workspace = root / "users" / admin_id
    workspace.mkdir(parents=True, exist_ok=True)
    journal_path = root / ADOPTION_JOURNAL
    operations = [
        {"name": name, "source": name, "target": name, "done": False}
        for name in _LEGACY_CHILDREN
        if (root / name).exists() or (workspace / name).exists()
    ]
    if (root / ".env").exists() or (workspace / "secrets.env").exists():
        operations.append(
            {"name": ".env", "source": ".env", "target": "secrets.env", "done": False}
        )
    if journal_path.is_file():
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        if journal.get("admin_id") != admin_id:
            raise AdoptionError("adoption journal belongs to a different admin")
        operations = journal["operations"]
    journal = {"admin_id": admin_id, "operations": operations}
    _write_journal(journal_path, journal)
    completed: list[dict] = []
    try:
        for operation in operations:
            source = root / operation["source"]
            target = workspace / operation["target"]
            if source.exists() and target.exists():
                raise AdoptionError(f"refusing to overwrite existing {target}")
            if source.exists():
                shutil.move(str(source), str(target))
                operation["done"] = True
                completed.append(operation)
                _write_journal(journal_path, journal)
            elif target.exists():
                operation["done"] = True
            else:
                operation["done"] = True
        journal_path.unlink(missing_ok=True)
        return [operation["name"] for operation in operations]
    except BaseException as error:
        rollback_failed = False
        for operation in reversed(completed):
            source = root / operation["source"]
            target = workspace / operation["target"]
            try:
                if target.exists() and not source.exists():
                    shutil.move(str(target), str(source))
                    operation["done"] = False
            except OSError:
                rollback_failed = True
        if rollback_failed:
            _write_journal(journal_path, journal)
            raise AdoptionError(
                f"legacy adoption failed and rollback was incomplete; resume from {journal_path}"
            ) from error
        journal_path.unlink(missing_ok=True)
        raise AdoptionError("legacy adoption failed and was rolled back") from error
