from __future__ import annotations

import asyncio
from pathlib import Path


class LocalFileStorage:
    """ADR-0008: dev backend, a plain directory outside the repo. Keys
    (`{org_id}/{uuid7}{ext}`, platform/files.py) are never derived from
    user input, so there is no path-traversal surface to defend against
    here."""

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        path = self._base_dir / key
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    async def put(self, key: str, data: bytes, *, content_type: str) -> None:
        await asyncio.to_thread(self._path_for(key).write_bytes, data)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path_for(key).read_bytes)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._path_for(key).unlink, missing_ok=True)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path_for(key).exists)
