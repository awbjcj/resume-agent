"""Bounded multipart upload helpers."""

from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

from fastapi import UploadFile


class UploadTooLargeError(ValueError):
    pass


def copy_upload(
    upload: UploadFile,
    destination: Path | BinaryIO,
    *,
    max_bytes: int,
    chunk_size: int = 1024 * 1024,
) -> int:
    close = False
    if isinstance(destination, Path):
        stream = destination.open("wb")
        close = True
    else:
        stream = destination
    written = 0
    try:
        while chunk := upload.file.read(chunk_size):
            written += len(chunk)
            if written > max_bytes:
                raise UploadTooLargeError(
                    f"upload exceeds the {max_bytes // (1024 * 1024)} MB limit"
                )
            stream.write(chunk)
    finally:
        if close:
            stream.close()
    return written


def read_upload(upload: UploadFile, *, max_bytes: int) -> bytes:
    from io import BytesIO

    buffer = BytesIO()
    copy_upload(upload, buffer, max_bytes=max_bytes)
    return buffer.getvalue()


async def read_upload_async(upload: UploadFile, *, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(1024 * 1024):
        total += len(chunk)
        if total > max_bytes:
            raise UploadTooLargeError(
                f"upload exceeds the {max_bytes // (1024 * 1024)} MB limit"
            )
        chunks.append(chunk)
    return b"".join(chunks)
