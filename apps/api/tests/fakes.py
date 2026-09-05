from __future__ import annotations

from trinol.modules.identity.identity_verifier import IdentityVerificationError, VerifiedIdentity


class FakeIdentityVerifier:
    """Test double for IdentityVerifier — never touches the network
    (ADR-0013 Consequences: "Tests must not call Firebase.")."""

    def __init__(self) -> None:
        self._tokens: dict[str, VerifiedIdentity] = {}

    def register(self, token: str, identity: VerifiedIdentity) -> None:
        self._tokens[token] = identity

    async def verify(self, id_token: str) -> VerifiedIdentity:
        try:
            return self._tokens[id_token]
        except KeyError:
            raise IdentityVerificationError(f"unknown fake token: {id_token}") from None
