"""Phase 10 P10-7 — /settings endpoints.

Reads and writes the YAML config files under ``config/``. Each ``kind``
maps to one file:

  settings        → settings.yaml         (committed defaults)
  weights         → weights.yaml          (Phase 9.1 scoring weights)
  tier_rules      → tier_rules.yaml       (tier thresholds)
  competitors     → competitors.yaml      (Phase 8 competitor list)
  intent_tiers    → intent_tiers.yaml     (Phase 8 related-channel intent)
  sector_leaders  → sector_leaders.yaml   (Phase 9.1 mega-cap bias seed)
  targets         → targets.yaml          (gitignored user data)

PUT validates the body in two passes — YAML parse (422 on syntax) and
pydantic-model construction for the corresponding schema (422 on shape).
On success the file is replaced atomically and the loader's lru_cache is
invalidated so subsequent reads pick up the new values.

Module-attr access only (``from src.config import loader as
_config_loader``) per the DO NOT rule.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException, status

from src.api.schemas import (
    SETTINGS_KINDS,
    SecretsView,
    SettingsKindList,
    SettingsRead,
    SettingsUpdate,
)
from src.config import loader as _config_loader
from src.config.schemas import (
    CompetitorsConfig,
    CostBudget,
    IntentTiersConfig,
    Pricing,
    SectorLeadersConfig,
    Settings,
    Targets,
    TierRulesConfig,
    WeightsConfig,
)


_LOGGER = logging.getLogger(__name__)
router = APIRouter()


# Each kind → (filename, validator). Validator is a pydantic-model type
# whose __init__ accepts the parsed dict and raises ValidationError on
# bad shape.
_KIND_TO_FILE: dict[str, str] = {
    "settings": "settings.yaml",
    "weights": "weights.yaml",
    "tier_rules": "tier_rules.yaml",
    "competitors": "competitors.yaml",
    "intent_tiers": "intent_tiers.yaml",
    "sector_leaders": "sector_leaders.yaml",
    "targets": "targets.yaml",
    "pricing": "pricing.yaml",
    "cost_budget": "cost_budget.yaml",
}


_KIND_TO_VALIDATOR: dict[str, type] = {
    "settings": Settings,
    "weights": WeightsConfig,
    "tier_rules": TierRulesConfig,
    "competitors": CompetitorsConfig,
    "intent_tiers": IntentTiersConfig,
    "sector_leaders": SectorLeadersConfig,
    "targets": Targets,
    "pricing": Pricing,
    "cost_budget": CostBudget,
}


def _config_dir() -> Path:
    """Resolve the config directory at call time so tests can monkeypatch
    ``_config_loader.CONFIG_DIR`` to a tmp path."""
    return Path(_config_loader.CONFIG_DIR)


def _path_for(kind: str) -> Path:
    if kind not in _KIND_TO_FILE:
        raise HTTPException(
            status_code=404,
            detail=(
                f"unknown settings kind {kind!r}; "
                f"valid kinds: {sorted(_KIND_TO_FILE.keys())}"
            ),
        )
    return _config_dir() / _KIND_TO_FILE[kind]


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _invalidate_caches() -> None:
    """Clear loader-side lru_caches so the next read sees fresh yaml.

    Only `get_settings` / `get_secrets` are lru_cached today. The other
    `load_*` helpers re-read the file on every call — no cache to clear.
    """
    try:
        _config_loader.get_settings.cache_clear()
    except AttributeError:
        pass
    try:
        _config_loader.get_secrets.cache_clear()
    except AttributeError:
        pass


@router.get("/settings", response_model=SettingsKindList)
async def list_settings_kinds() -> SettingsKindList:
    return SettingsKindList(kinds=list(SETTINGS_KINDS))  # type: ignore[arg-type]


@router.get("/settings/secrets", response_model=SecretsView)
async def get_secrets_view() -> SecretsView:
    secrets = _config_loader.get_secrets()
    return SecretsView(
        anthropic_api_key=bool(getattr(secrets, "anthropic_api_key", "")),
        brave_search_api_key=bool(getattr(secrets, "brave_search_api_key", "")),
        notion_token=bool(getattr(secrets, "notion_token", "")),
    )


@router.get("/settings/{kind}", response_model=SettingsRead)
async def read_settings(kind: str) -> SettingsRead:
    path = _path_for(kind)
    if not path.exists():
        return SettingsRead(
            kind=kind,  # type: ignore[arg-type]
            path=str(path),
            exists=False,
            raw_yaml="",
            parsed=None,
        )
    raw = path.read_text(encoding="utf-8")
    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        _LOGGER.warning("settings: %s parse failed: %s", path, exc)
        parsed = None
    if parsed is not None and not isinstance(parsed, dict):
        # Top-level should be a mapping for all our kinds; coerce anything
        # else to None so the UI knows to render it raw-only.
        parsed = None
    return SettingsRead(
        kind=kind,  # type: ignore[arg-type]
        path=str(path),
        exists=True,
        raw_yaml=raw,
        parsed=parsed,
    )


@router.put("/settings/{kind}", response_model=SettingsRead)
async def write_settings(kind: str, payload: SettingsUpdate) -> SettingsRead:
    path = _path_for(kind)
    raw = payload.raw_yaml

    # Pass 1: YAML syntax
    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise HTTPException(
            status_code=422, detail=f"YAML parse error: {exc}"
        ) from exc
    if parsed is None:
        parsed = {}
    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=422,
            detail="top-level YAML must be a mapping (dict)",
        )

    # Pass 2: pydantic-model shape
    validator = _KIND_TO_VALIDATOR[kind]
    try:
        validator(**parsed)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"validation failed for {kind!r}: {exc}",
        ) from exc

    _atomic_write_text(path, raw)
    _invalidate_caches()

    return SettingsRead(
        kind=kind,  # type: ignore[arg-type]
        path=str(path),
        exists=True,
        raw_yaml=raw,
        parsed=parsed,
    )
