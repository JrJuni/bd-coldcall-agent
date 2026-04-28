"""Phase 8 — shared types for the multi-channel search layer.

`IntentSpec` is the runtime form of one entry in `config/intent_tiers.yaml`:
a label + S/A/B/C tier + per-language keywords. The Related channel turns
each spec into 1+ Brave queries weighted by tier.

`CompetitorSpec` is the runtime form of `config/competitors.yaml` entries.
direct vs adjacent is preserved as `weight` so future ranking layers can
prefer direct hits without re-reading the yaml.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


Tier = Literal["S", "A", "B", "C"]


@dataclass(frozen=True)
class IntentSpec:
    label: str
    tier: Tier
    description: str = ""
    keywords_ko: tuple[str, ...] = field(default_factory=tuple)
    keywords_en: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CompetitorSpec:
    name: str
    weight: float  # 1.0 for direct, 0.6 for adjacent
    relation: Literal["direct", "adjacent"]
