from __future__ import annotations

from trinol.modules.identity.firebase_verifier import FirebaseIdentityVerifier
from trinol.modules.identity.identity_verifier import IdentityVerifier

_verifier: IdentityVerifier | None = None


def get_identity_verifier() -> IdentityVerifier:
    """Overridden in tests via `app.dependency_overrides` with a
    `FakeIdentityVerifier` (ADR-0013: tests must not call Firebase)."""
    global _verifier
    if _verifier is None:
        _verifier = FirebaseIdentityVerifier()
    return _verifier
