"""Settings-only bundle: export, preview, and section-level import.

A bundle carries exactly the sections declared in settings_sections.py --
never the database, the derived profile corpus, or any credential. Import
replaces the sections a bundle names and leaves every other section untouched,
so a bundle can add or replace settings but never clear them. Clearing is what
reset is for.
"""

from __future__ import annotations

import io
import json
import tarfile
from datetime import UTC, datetime
from pathlib import Path

from resume_agent.settings_sections import (
    SETTINGS_SECTIONS,
    arcname_for,
    live_paths,
)

BUNDLE_VERSION = 1
MANIFEST_NAME = "manifest.json"


class InvalidBundleError(ValueError):
    """The upload is not a readable settings bundle."""


class UnsupportedBundleVersionError(InvalidBundleError):
    """The bundle was written by a version this build does not understand."""


def export_settings_bundle(out_dir: Path) -> Path:
    """Write a tar.gz of every populated section into `out_dir`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC)
    archive = out_dir / f"resume-agent-settings-{stamp.date().isoformat()}.tar.gz"

    sections: list[str] = []
    members: list[tuple[str, Path]] = []
    for section in SETTINGS_SECTIONS:
        found = [
            (arcname_for(entry, path), path)
            for entry in section.files
            for path in live_paths(entry)
        ]
        if found:
            sections.append(section.id)
            members.extend(found)

    manifest = json.dumps(
        {
            "version": BUNDLE_VERSION,
            "exportedAt": stamp.isoformat(),
            "sections": sections,
        },
        indent=2,
    ).encode("utf-8")

    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo(MANIFEST_NAME)
        info.size = len(manifest)
        info.mtime = int(stamp.timestamp())
        tar.addfile(info, io.BytesIO(manifest))
        for arcname, path in members:
            tar.add(path, arcname=arcname)
    return archive
