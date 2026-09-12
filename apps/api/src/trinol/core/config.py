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

    # Phase 2 Stage 11 (Playwright E2E): lets get_identity_verifier() (deps.py)
    # return E2EIdentityVerifier instead of the real Firebase one, so an
    # externally-running server can authenticate a Playwright browser
    # without real Firebase credentials. Double-gated at the call site
    # (never honored when app_env == "production", regardless of this
    # flag) — same defense-in-depth posture as EMAIL.md §3's dev-only SMTP
    # allowlist.
    e2e_test_mode: bool = False

    storage_backend: Literal["local", "s3"] = "local"
    # ADR-0008: "a directory outside the repo" — relative paths resolve
    # under whatever the process's cwd is (apps/api locally, /app in
    # Docker), and both `storage/` and `uploads/` are already gitignored
    # at any depth, so this is never accidentally committed either way.
    local_storage_dir: str = "storage/uploads"
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
    # EMAIL.md §3: "non-production environments refuse to send to any address
    # outside an allowlist, so a seeded database can never mail a real
    # client." Comma-separated; checked only when app_env != "production".
    smtp_dev_allowlist: str | None = None

    public_contact_org_slug: str | None = None
    # SECURITY.md §5: the one endpoint OriginCheckMiddleware allows a
    # different origin for. None until Phase 3 builds the route and this is
    # actually configured — no code change needed then, only this env var.
    public_contact_origin: str | None = None

    # ADR-0014: Phase 8 AI. Absent in dev/CI until provided — ai/services/
    # deps.py inits lazily and only raises if a real OpenAI call is actually
    # made without it (same posture as firebase_credentials above); tests
    # never reach that code path since fake_ai_client overrides the
    # dependency entirely.
    openai_api_key: str | None = None
    openai_chat_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
