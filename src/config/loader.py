import logging
from functools import lru_cache
from pathlib import Path

import yaml

from .schemas import (
    CompetitorsConfig,
    IntentTiersConfig,
    Secrets,
    Settings,
    Targets,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"

_LOGGER = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_secrets() -> Secrets:
    return Secrets()


@lru_cache(maxsize=1)
def get_settings(path: Path | None = None) -> Settings:
    path = path or (CONFIG_DIR / "settings.yaml")
    with open(path, encoding="utf-8") as f:
        return Settings(**yaml.safe_load(f))


def get_targets(path: Path | None = None) -> Targets:
    path = path or (CONFIG_DIR / "targets.yaml")
    if not path.exists():
        example = CONFIG_DIR / "targets.example.yaml"
        raise FileNotFoundError(
            f"{path} not found. Copy {example.name} to {path.name} and edit your targets."
        )
    with open(path, encoding="utf-8") as f:
        return Targets(**yaml.safe_load(f))


def load_competitors(path: Path | None = None) -> CompetitorsConfig:
    """Load `config/competitors.yaml`.

    Missing file or empty body returns an empty config + warn — the
    Competitor channel then yields zero articles without raising. This
    keeps the search pipeline runnable on a fresh checkout.
    """
    path = path or (CONFIG_DIR / "competitors.yaml")
    if not path.exists():
        _LOGGER.warning(
            "competitors.yaml not found at %s — competitor channel disabled. "
            "Copy competitors.example.yaml to enable.",
            path,
        )
        return CompetitorsConfig()
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return CompetitorsConfig(**data)


def load_intent_tiers(path: Path | None = None) -> IntentTiersConfig:
    """Load `config/intent_tiers.yaml` for the Related channel.

    Missing or empty file → empty config + warn. Run
    `scripts/draft_intent_tiers.py` to generate a starting yaml.
    """
    path = path or (CONFIG_DIR / "intent_tiers.yaml")
    if not path.exists():
        _LOGGER.warning(
            "intent_tiers.yaml not found at %s — related channel disabled. "
            "Run `python -m scripts.draft_intent_tiers` to generate a draft.",
            path,
        )
        return IntentTiersConfig()
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return IntentTiersConfig(**data)
