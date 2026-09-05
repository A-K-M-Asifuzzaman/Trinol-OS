from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class VerifiedIdentity:
    """What we trust from a verified Firebase ID token — nothing more.

    `sign_in_provider` is Firebase's raw claim ("password" | "google.com"),
    mapped to our `AuthProvider` enum in the service layer, not here — this
    module knows nothing about our schema.
    """

    firebase_uid: str
    email: str
    email_verified: bool
    sign_in_provider: str
    full_name: str | None
    avatar_url: str | None


class IdentityVerificationError(Exception):
    """The token is missing, malformed, expired, or minted for a different
    Firebase project. Never raised for a valid-but-unverified-email token —
    that's a successful verification the caller has policy reasons to reject
    (AUTH.md §5 step 2)."""


class IdentityVerifier(Protocol):
    async def verify(self, id_token: str) -> VerifiedIdentity: ...
