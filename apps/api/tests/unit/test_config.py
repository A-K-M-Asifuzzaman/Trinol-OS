from __future__ import annotations

import pytest

from trinol.core.config import Settings, _find_env_file


def test_find_env_file_locates_real_repo_root_env() -> None:
    assert _find_env_file() is not None


def test_find_env_file_returns_none_without_crashing_when_none_found(tmp_path) -> None:
    """Regression test: config.py used to compute
    Path(__file__).resolve().parents[5], assuming the full monorepo is
    mounted. Docker only mounts apps/api at /app, so that index is out of
    range there — IndexError at import time, before any environment variable
    is even read. This simulates that layout: a deep, isolated tmp_path with
    no .env anywhere above it in the chain."""
    isolated = tmp_path / "app" / "src" / "trinol" / "core" / "config.py"
    assert _find_env_file(start=isolated) is None


def test_settings_construct_from_real_env_vars_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Docker case end-to-end: no .env file, only real process env vars
    (which is exactly what `env_file:`/`environment:` in docker-compose.yml
    provides) — Settings must still construct."""
    monkeypatch.setenv("APP_ORIGIN", "http://localhost:3000")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.app_origin == "http://localhost:3000"
    assert settings.database_url == "postgresql+asyncpg://x:x@localhost/x"
