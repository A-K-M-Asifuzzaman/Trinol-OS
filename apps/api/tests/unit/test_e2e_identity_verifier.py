from __future__ import annotations

from types import SimpleNamespace

import pytest

import trinol.modules.identity.deps as deps_module
from trinol.modules.identity.e2e_verifier import E2EIdentityVerifier
from trinol.modules.identity.firebase_verifier import FirebaseIdentityVerifier

# Stage 11 (Playwright E2E): get_identity_verifier() must only ever hand out
# E2EIdentityVerifier when e2e_test_mode is genuinely on *and* app_env isn't
# production — a security-relevant gate (an auth bypass, even a narrow one)
# gets the same direct-test treatment as origin_check/authz_matrix.


@pytest.fixture(autouse=True)
def _reset_verifier_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_identity_verifier() caches its result in a module-level global —
    reset it before and after each test so one test's monkeypatched Settings
    can't leak into another's."""
    monkeypatch.setattr(deps_module, "_verifier", None)


def _fake_settings(*, e2e_test_mode: bool, app_env: str) -> SimpleNamespace:
    return SimpleNamespace(e2e_test_mode=e2e_test_mode, app_env=app_env)


async def test_e2e_verifier_returns_the_seed_scripts_firebase_uid_scheme() -> None:
    identity = await E2EIdentityVerifier().verify("founder@trinolit.com")
    assert identity.firebase_uid == "seed-founder@trinolit.com"
    assert identity.email == "founder@trinolit.com"
    assert identity.email_verified is True
    assert identity.sign_in_provider == "password"


def test_get_identity_verifier_uses_e2e_verifier_when_enabled_outside_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        deps_module,
        "get_settings",
        lambda: _fake_settings(e2e_test_mode=True, app_env="local"),
    )
    assert isinstance(deps_module.get_identity_verifier(), E2EIdentityVerifier)


def test_get_identity_verifier_ignores_e2e_flag_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        deps_module,
        "get_settings",
        lambda: _fake_settings(e2e_test_mode=True, app_env="production"),
    )
    assert isinstance(deps_module.get_identity_verifier(), FirebaseIdentityVerifier)


def test_get_identity_verifier_defaults_to_firebase_when_e2e_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        deps_module,
        "get_settings",
        lambda: _fake_settings(e2e_test_mode=False, app_env="local"),
    )
    assert isinstance(deps_module.get_identity_verifier(), FirebaseIdentityVerifier)
