from __future__ import annotations

from typing import Protocol


class FileStorage(Protocol):
    """ADR-0008: one interface, two implementations (local/S3), selected by
    `STORAGE_BACKEND`. Keys are `{org_id}/{uuid7}{ext}` (platform/files.py) —
    never the user's filename, which lives only in `file_objects.filename`."""

    async def put(self, key: str, data: bytes, *, content_type: str) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...
    async def exists(self, key: str) -> bool: ...
