# ADR-0008 — File storage abstraction

Status: Accepted (Phase 0)

## Context

MASTER_PROMPT §24 asks for a storage abstraction, local or S3-compatible in
development and S3-compatible in production, with validation of size, MIME,
extension and filenames.

## Decision

A `FileStorage` protocol with `put`, `get`, `delete`, `exists`. Two
implementations: `LocalFileStorage` (dev, a directory outside the repo) and
`S3FileStorage` (`boto3`, works against MinIO, Backblaze B2, Cloudflare R2 and
S3). Selected by `STORAGE_BACKEND`.

Metadata lives in `file_objects`; the blob lives in storage. Storage keys are
`{org_id}/{uuid7}{ext}` — the user's filename is data, never a path.

**Uploads go through the API** in V1, which is where validation happens: size
cap, extension allowlist, and content-type *sniffed* from the bytes rather than
trusted from the client. Mismatch is rejected.

**Downloads go through an authorized API route** that checks organization and
resource access, then streams the object with
`Content-Disposition: attachment` and `X-Content-Type-Options: nosniff`. No
public bucket, no guessable URL.

## Alternatives rejected

**Presigned direct-to-S3 uploads.** The right answer for large files and high
volume: it takes the bytes off the API host. Deferred because it moves
validation *after* the object exists (so the pipeline needs a
quarantine-then-promote flow), needs CORS on the bucket, and the files here are
receipts and screenshots. `ponytail: proxied uploads; move to presigned PUT if
uploads exceed ~25 MiB or the API host becomes the bottleneck.`

**Storing blobs in PostgreSQL.** Bloats the database and its backups.

**A third "cloud provider SDK" implementation.** S3-compatible covers every
realistic target.

## Consequences

- One interface, two implementations, no speculative third.
- Attachment access is authorized by the same rules as its parent resource,
  because it is fetched through the same application.
- Deleting a database row must also delete the object; a periodic orphan sweep
  is the backstop, since the two stores cannot be transactional together.
