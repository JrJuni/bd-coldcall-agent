"""Phase 7 — FastAPI runtime config.

Small env-driven knobs kept out of `settings.yaml` because they change per
deployment / test run, not per target company.

- `API_SKIP_WARMUP=1` skips the Exaone + bge-m3 preload in `lifespan` so
  tests don't pay a 30s GPU load.
- `API_CHECKPOINT_DB` points at the SqliteSaver DB (Phase 7 Stream 4).
- `API_CORS_ORIGINS` is a comma-separated allowlist. Defaults to the
  Next.js dev server at :3000.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if not raw:
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class ApiSettings:
    skip_warmup: bool
    checkpoint_db: Path
    app_db: Path
    cors_origins: list[str]


@lru_cache(maxsize=1)
def get_api_settings() -> ApiSettings:
    return ApiSettings(
        skip_warmup=_env_bool("API_SKIP_WARMUP", False),
        checkpoint_db=Path(os.getenv("API_CHECKPOINT_DB", "data/checkpoints.db")),
        app_db=Path(os.getenv("API_APP_DB", "data/app.db")),
        cors_origins=_env_list("API_CORS_ORIGINS", ["http://localhost:3000"]),
    )


def reset_api_settings_cache() -> None:
    """Test hook — drop the cached settings so env changes take effect."""
    get_api_settings.cache_clear()
