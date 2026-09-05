from __future__ import annotations

from functools import lru_cache

from trinol.core.config import Settings


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # fields load from env/.env
