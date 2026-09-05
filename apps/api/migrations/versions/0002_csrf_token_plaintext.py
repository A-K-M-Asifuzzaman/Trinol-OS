"""sessions.csrf_hash -> csrf_token (stored in plaintext)

Revision ID: 0002_csrf_token_plaintext
Revises: 0001_initial
Create Date: 2026-09-06

Phase 0 named this column `csrf_hash` and Stage 4 stored a one-way
sha256(csrf_token) in it, matching `token_hash`'s pattern. But AUTH.md §6
requires the *raw* value to be returned from `GET /api/v1/auth/session` for
the double-submit check — impossible to recover from a one-way hash. This
was a genuine design error, caught while implementing the GET endpoint that
needs to read it back, not a discovered vulnerability: unlike the session
token (whose possession alone grants access, so it must never be readable
from a compromised DB), the CSRF token's security comes from the browser's
same-origin policy blocking a cross-site page from reading the response body
or setting the X-CSRF-Token header — not from secrecy at rest. Storing it in
plaintext is standard practice for this exact pattern (Django, Rails do the
same for their CSRF tokens).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_csrf_token_plaintext"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE sessions RENAME COLUMN csrf_hash TO csrf_token")


def downgrade() -> None:
    op.execute("ALTER TABLE sessions RENAME COLUMN csrf_token TO csrf_hash")
