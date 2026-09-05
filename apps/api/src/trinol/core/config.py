from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env_file(start: Path | None = None) -> str | None:
    """Walk upward from `start` (default: this file) looking for a `.env`,
    instead of a fixed `parents[N]` — a hardcoded depth matches the host
    layout (repo root five levels up) but not Docker's, where only apps/api
    is mounted at /app and no `.env` exists at any ancestor. `Path.parents`
    terminates at the filesystem root on its own, so this can't raise the way
    indexing a fixed offset did; it just finds nothing and returns None,
    which tells pydantic-settings to skip dotenv loading and read real env
    vars only — exactly what Compose already injects via
    `env_file:`/`environment:`.
    """
    for directory in (start or Path(__file__).resolve()).parents:
        candidate = directory / ".env"
        if candidate.is_file():
            return str(candidate)
    return None


_ENV_FILE = _find_env_file()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    app_env: Literal["local", "staging", "production"] = "local"
    api_port: int = 8000
    app_origin: str
    session_cookie_name: str = "trinol_session"

    database_url: str

    # Absent in dev until provided (docs/adr/0013): FirebaseIdentityVerifier
    # inits lazily and only raises if the real exchange endpoint is hit
    # without it. Settings must not fail boot over this.
    firebase_credentials: str | None = None

    storage_backend: Literal["local", "s3"] = "local"
    s3_endpoint: str | None = None
    s3_bucket: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_region: str | None = None

    email_backend: Literal["console", "memory", "smtp"] = "console"
    smtp_host: str | None = None
    smtp_port: int = 465
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_from_name: str | None = None

    public_contact_org_slug: str | None = None
    # SECURITY.md §5: the one endpoint OriginCheckMiddleware allows a
    # different origin for. None until Phase 3 builds the route and this is
    # actually configured — no code change needed then, only this env var.
    public_contact_origin: str | None = None
