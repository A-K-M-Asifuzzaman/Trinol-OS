from __future__ import annotations

from pathlib import Path

from trinol.core.deps import get_settings
from trinol.platform.file_storage.local import LocalFileStorage
from trinol.platform.file_storage.protocol import FileStorage
from trinol.platform.file_storage.s3 import S3FileStorage

_storage: FileStorage | None = None


def get_file_storage() -> FileStorage:
    """ADR-0008, selected by `STORAGE_BACKEND`. Overridden in tests via
    `app.dependency_overrides` (same pattern as get_email_sender/
    get_identity_verifier) — the automated suite never touches a real S3
    endpoint; its `LocalFileStorage` case uses a real temp directory
    instead of this function's configured path.
    """
    global _storage
    if _storage is None:
        settings = get_settings()
        if settings.storage_backend == "s3":
            _storage = S3FileStorage(
                bucket=settings.s3_bucket or "",
                endpoint_url=settings.s3_endpoint,
                access_key_id=settings.s3_access_key_id or "",
                secret_access_key=settings.s3_secret_access_key or "",
                region=settings.s3_region,
            )
        else:
            _storage = LocalFileStorage(Path(settings.local_storage_dir))
    return _storage
