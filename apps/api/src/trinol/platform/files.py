from __future__ import annotations

import hashlib
import uuid
from pathlib import PurePosixPath

from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.db.org_session import OrgSession
from trinol.core.errors import UnprocessableEntityError
from trinol.core.ids import uuid7
from trinol.platform.file_storage.protocol import FileStorage
from trinol.platform.models import FileObject

# SECURITY.md §6: 10 MiB default size cap, extension allowlist, sniffed
# content type (the client's Content-Type header is a hint, not evidence).
# SVG is deliberately absent — scriptable, rejected for avatars and
# attachments — and is rejected by this same general mechanism (no magic
# signature matches XML text), not a special case.
_MAX_SIZE_BYTES = 10 * 1024 * 1024

# Each signature maps to the one content type and set of extensions it may
# legally be uploaded under; a mismatch (e.g. a PDF renamed to .png) is
# rejected, not silently corrected.
_SIGNATURES: tuple[tuple[bytes, str, frozenset[str]], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png", frozenset({".png"})),
    (b"\xff\xd8\xff", "image/jpeg", frozenset({".jpg", ".jpeg"})),
    (b"%PDF-", "application/pdf", frozenset({".pdf"})),
)
_ALLOWED_EXTENSIONS = frozenset({ext for _, _, exts in _SIGNATURES for ext in exts} | {".webp"})


def _sniff(data: bytes) -> tuple[str, frozenset[str]] | None:
    # WebP's signature isn't a fixed prefix (bytes 4-7 are a length field),
    # so it needs its own check rather than fitting the plain-prefix table.
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", frozenset({".webp"})
    for magic, content_type, extensions in _SIGNATURES:
        if data.startswith(magic):
            return content_type, extensions
    return None


def _validate_upload(filename: str, data: bytes) -> str:
    """Returns the sniffed content type, or raises `UnprocessableEntityError`
    (SECURITY.md §6)."""
    if len(data) > _MAX_SIZE_BYTES:
        raise UnprocessableEntityError(f"File exceeds the {_MAX_SIZE_BYTES}-byte limit")

    extension = PurePosixPath(filename).suffix.lower()
    if extension not in _ALLOWED_EXTENSIONS:
        raise UnprocessableEntityError(f"File extension {extension!r} is not allowed")

    sniffed = _sniff(data)
    if sniffed is None:
        raise UnprocessableEntityError("File content does not match a supported type")
    content_type, valid_extensions = sniffed
    if extension not in valid_extensions:
        raise UnprocessableEntityError("File extension does not match its actual content type")
    return content_type


async def create_file_object(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    uploaded_by: uuid.UUID,
    filename: str,
    data: bytes,
    storage: FileStorage,
) -> FileObject:
    """Validates, stores the blob, and inserts the `file_objects` row —
    does *not* commit, so the caller can add its own row (e.g.
    `TaskAttachment`) in the same transaction (ADR-0006's pattern, applied
    here to file metadata instead of activity events)."""
    content_type = _validate_upload(filename, data)
    extension = PurePosixPath(filename).suffix.lower()
    # ADR-0008: never the user's filename — that's stored separately below.
    storage_key = f"{organization_id}/{uuid7()}{extension}"
    checksum = hashlib.sha256(data).hexdigest()

    await storage.put(storage_key, data, content_type=content_type)

    org_session = OrgSession(db, organization_id=organization_id)
    file_object = FileObject(
        id=uuid7(),
        storage_key=storage_key,
        filename=filename,
        content_type=content_type,
        size_bytes=len(data),
        checksum_sha256=checksum,
        uploaded_by=uploaded_by,
    )
    org_session.add(file_object)
    await db.flush()
    return file_object
