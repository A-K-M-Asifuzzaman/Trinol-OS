from __future__ import annotations

import firebase_admin
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials
from starlette.concurrency import run_in_threadpool

from trinol.core.deps import get_settings
from trinol.modules.identity.identity_verifier import (
    IdentityVerificationError,
    VerifiedIdentity,
)

_app: firebase_admin.App | None = None


def _get_app() -> firebase_admin.App:
    """Lazy init (ADR-0013): a missing FIREBASE_CREDENTIALS must not fail app
    boot or Settings construction. Only an actual call to the real exchange
    endpoint without it should ever raise, and only then."""
    global _app
    if _app is not None:
        return _app

    settings = get_settings()
    if not settings.firebase_credentials:
        raise IdentityVerificationError(
            "FIREBASE_CREDENTIALS is not set; cannot verify a real Firebase ID token."
        )
    cred = credentials.Certificate(settings.firebase_credentials)
    _app = firebase_admin.initialize_app(cred)
    return _app


class FirebaseIdentityVerifier:
    async def verify(self, id_token: str) -> VerifiedIdentity:
        app = _get_app()
        try:
            # verify_id_token is offline (cached Google public keys, no
            # per-request network call — AUTH.md §5) but it's still a sync
            # call from firebase_admin, which has no async API; run it off
            # the event loop rather than assume it never blocks.
            decoded = await run_in_threadpool(firebase_auth.verify_id_token, id_token, app=app)
        except Exception as exc:  # firebase_admin raises several distinct types
            raise IdentityVerificationError(str(exc)) from exc

        firebase_claims = decoded.get("firebase", {})
        return VerifiedIdentity(
            firebase_uid=decoded["uid"],
            email=decoded.get("email", ""),
            email_verified=bool(decoded.get("email_verified", False)),
            sign_in_provider=firebase_claims.get("sign_in_provider", "password"),
            full_name=decoded.get("name"),
            avatar_url=decoded.get("picture"),
        )
