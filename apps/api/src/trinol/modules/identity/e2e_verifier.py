from __future__ import annotations

from trinol.modules.identity.identity_verifier import VerifiedIdentity


class E2EIdentityVerifier:
    """Test-only `IdentityVerifier`, active only when `Settings.e2e_test_mode`
    is on (and never in production — deps.py double-checks `app_env` at the
    call site). Lets Playwright authenticate against a real, externally
    running server with no real Firebase project of its own to verify
    against.

    `id_token` here is just the plain email of a pre-existing (typically
    seeded) user — no real Firebase round-trip. `firebase_uid` mirrors
    `scripts/seed.py`'s own placeholder scheme (`f"seed-{email}"`) so this
    resolves to that exact seeded user via `_resolve_or_provision_user`'s
    firebase_uid lookup, not a freshly-provisioned one.
    """

    async def verify(self, id_token: str) -> VerifiedIdentity:
        email = id_token
        return VerifiedIdentity(
            firebase_uid=f"seed-{email}",
            email=email,
            email_verified=True,
            sign_in_provider="password",
            full_name=None,
            avatar_url=None,
        )
