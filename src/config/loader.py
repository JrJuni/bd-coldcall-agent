import logging
from functools import lru_cache
from pathlib import Path

import yaml

from .schemas import (
    CompetitorsConfig,
    CostBudget,
    IntentTiersConfig,
    Pricing,
    RegionsConfig,
    Secrets,
    SectorLeadersConfig,
    Settings,
    Targets,
    TierRulesConfig,
    WeightsConfig,
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


def load_weights_config(path: Path | None = None) -> WeightsConfig:
    """Load `config/weights.yaml` — Phase 9.1 scoring weights.

    Bundled committed default; missing file is a config bug, not a soft warn.
    """
    path = path or (CONFIG_DIR / "weights.yaml")
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found — required for discovery scoring. "
            "Restore from repo or recreate from docs/architecture.md."
        )
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return WeightsConfig(**data)


def load_tier_rules_config(path: Path | None = None) -> TierRulesConfig:
    """Load `config/tier_rules.yaml` — Phase 9.1 tier thresholds."""
    path = path or (CONFIG_DIR / "tier_rules.yaml")
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found — required for discovery tier decisions. "
            "Restore from repo or recreate from docs/architecture.md."
        )
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return TierRulesConfig(**data)


def load_pricing(path: Path | None = None) -> Pricing:
    """Load `config/pricing.yaml` — Cost Explorer pricing table.

    Missing file → empty pricing + warn (Cost Explorer reports $0 on
    every run until the user populates it).
    """
    path = path or (CONFIG_DIR / "pricing.yaml")
    if not path.exists():
        _LOGGER.warning(
            "pricing.yaml not found at %s — Cost Explorer will report $0. "
            "Save default rates from the Cost page to populate.",
            path,
        )
        return Pricing()
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return Pricing(**data)


def load_cost_budget(path: Path | None = None) -> CostBudget:
    """Load `config/cost_budget.yaml` — monthly USD budget + warn threshold.

    Missing file falls back to schema defaults ($100/mo, 80%% warn).
    """
    path = path or (CONFIG_DIR / "cost_budget.yaml")
    if not path.exists():
        _LOGGER.warning(
            "cost_budget.yaml not found at %s — using $100/mo, 80%% warn defaults.",
            path,
        )
        return CostBudget()
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return CostBudget(**data)


def load_regions(path: Path | None = None) -> RegionsConfig:
    """Load `config/regions.yaml` — Phase 12 country master for Discovery.

    Missing file falls back to a built-in minimal default (the four major
    continent groups with one or two anchor countries each) so a fresh
    checkout still has something selectable. The committed yaml is not
    gitignored — it's a reference list, not user data.
    """
    path = path or (CONFIG_DIR / "regions.yaml")
    if not path.exists():
        _LOGGER.warning(
            "regions.yaml not found at %s — using minimal built-in fallback. "
            "Restore from repo to see the full country list.",
            path,
        )
        return RegionsConfig(
            version=1,
            groups=[
                {
                    "id": "north_america",
                    "label": "North America",
                    "countries": [{"code": "us", "label": "United States"}],
                },
                {
                    "id": "asia",
                    "label": "Asia",
                    "countries": [
                        {"code": "kr", "label": "South Korea"},
                        {"code": "jp", "label": "Japan"},
                    ],
                },
                {
                    "id": "europe",
                    "label": "Europe",
                    "countries": [
                        {"code": "gb", "label": "United Kingdom"},
                        {"code": "de", "label": "Germany"},
                    ],
                },
                {
                    "id": "oceania",
                    "label": "Oceania",
                    "countries": [{"code": "au", "label": "Australia"}],
                },
            ],
        )
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return RegionsConfig(**data)


def load_sector_leaders(path: Path | None = None) -> SectorLeadersConfig:
    """Load `config/sector_leaders.yaml` — Phase 9.1 mega-cap bias mitigation seed.

    Missing or empty file → empty config + warn (the seed block is simply
    skipped). Operational yaml is gitignored; commit only sector_leaders.example.yaml.
    """
    path = path or (CONFIG_DIR / "sector_leaders.yaml")
    if not path.exists():
        _LOGGER.warning(
            "sector_leaders.yaml not found at %s — sector_leader_seeds block disabled. "
            "Copy sector_leaders.example.yaml or run "
            "`python -m scripts.draft_sector_leaders` to generate a draft.",
            path,
        )
        return SectorLeadersConfig()
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return SectorLeadersConfig(**data)
