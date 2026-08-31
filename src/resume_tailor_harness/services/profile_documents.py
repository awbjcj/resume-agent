"""Manifest-backed profile document store (data/profile/documents/).

File first, manifest last: a crashed upload leaves an orphan directory but
never a manifest entry, so readers only ever see complete documents.
Designed for the profile-corpus spec's multi-doc ingestion; today only the
resume-typed document feeds profile build.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from resume_tailor_harness.security.paths import confined_path

ALLOWED_SUFFIXES = {".pdf", ".docx", ".txt", ".md"}
ALLOWED_DOC_TYPES = {"resume", "transcript", "portfolio", "other"}
MAX_SIZE_BYTES = 15 * 1024 * 1024


class DocumentError(Exception):
    """User-fixable upload problem: bad type, bad extension, too large."""


@dataclass(frozen=True)
class DocumentRecord:
    id: str
    filename: str
    doc_type: str
    size_bytes: int
    uploaded_at: str


def _safe_name(filename: str) -> str:
    name = Path(filename).name  # strip any client path
    return re.sub(r"[^A-Za-z0-9._-]", "_", name) or "upload"


class DocumentStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()

    @property
    def _manifest_path(self) -> Path:
        return confined_path(self.root, "manifest.json")

    def _document_dir(self, doc_id: str) -> Path:
        return confined_path(self.root, doc_id)

    def _document_path(self, doc_id: str, filename: str) -> Path:
        return confined_path(self._document_dir(doc_id), filename)

    def _read_manifest(self) -> list[dict]:
        if not self._manifest_path.exists():
            return []
        return json.loads(self._manifest_path.read_text(encoding="utf-8"))

    def _write_manifest(self, rows: list[dict]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self._manifest_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        os.replace(tmp, self._manifest_path)

    def add(self, filename: str, content: bytes, doc_type: str) -> DocumentRecord:
        if doc_type not in ALLOWED_DOC_TYPES:
            raise DocumentError(f"docType must be one of {sorted(ALLOWED_DOC_TYPES)}")
        name = _safe_name(filename)
        if Path(name).suffix.lower() not in ALLOWED_SUFFIXES:
            raise DocumentError(f"File type must be one of {sorted(ALLOWED_SUFFIXES)}")
        if len(content) > MAX_SIZE_BYTES:
            raise DocumentError("File exceeds the 15 MB limit")
        doc_id = uuid.uuid4().hex[:12]
        target_dir = self._document_dir(doc_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        self._document_path(doc_id, name).write_bytes(content)  # file first…
        record = DocumentRecord(
            id=doc_id,
            filename=name,
            doc_type=doc_type,
            size_bytes=len(content),
            uploaded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        rows = self._read_manifest()
        rows.append(asdict(record))
        self._write_manifest(rows)  # …manifest last
        return record

    def list(self) -> list[DocumentRecord]:
        return [DocumentRecord(**row) for row in self._read_manifest()]

    def delete(self, doc_id: str) -> bool:
        rows = self._read_manifest()
        kept = [r for r in rows if r["id"] != doc_id]
        if len(kept) == len(rows):
            return False
        self._write_manifest(kept)
        target = self._document_dir(doc_id)
        if target.is_dir():
            for child in target.iterdir():
                child.unlink(missing_ok=True)
            target.rmdir()
        return True

    def latest_resume_path(self) -> Path | None:
        resumes = [r for r in self._read_manifest() if r["doc_type"] == "resume"]
        if not resumes:
            return None
        # uploaded_at has second precision, so ties are possible; break ties by
        # manifest order (later appends win) instead of silently keeping the first.
        _, newest = max(
            enumerate(resumes), key=lambda pair: (pair[1]["uploaded_at"], pair[0])
        )
        return self._document_path(newest["id"], newest["filename"])
