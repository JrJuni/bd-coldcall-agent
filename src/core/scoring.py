"""Phase 9.1 — Discovery scoring engine.

LLM emits 0-10 integer scores per dimension; this module decides the final
score and tier deterministically. The split lets weights / thresholds live in
external yaml so re-running with different weights costs $0 — no Sonnet call,
no re-prompting, just `for c in candidates: c.final_score = ...; c.tier = ...`.

Dimension list, default weights, and tier thresholds are user-editable in
`config/weights.yaml` and `config/tier_rules.yaml`. Per-product overrides
under `weights.yaml::products.<name>` partial-override the default — missing
dimensions inherit. The merged weight vector is auto-normalized so any
absolute drift from 1.0 doesn't silently rescale `final_score` outside 0-10.
"""
from __future__ import annotations

import logging
from typing import Literal

from src.config import loader as _loader


_LOGGER = logging.getLogger(__name__)


# Locked dimension order. New dimensions require yaml + this constant + prompt
# update — keeping it explicit in code avoids silent drift.
WEIGHT_DIMENSIONS: tuple[str, ...] = (
    "pain_severity",
    "data_complexity",
    "governance_need",
    "ai_maturity",
    "buying_trigger",
    "displacement_ease",
)


Tier = Literal["S", "A", "B", "C"]
TIER_VALUES: tuple[str, ...] = ("S", "A", "B", "C")


def load_weights(product: str | None = None) -> dict[str, float]:
    """Resolve effective weight vector for `product`.

    Steps:
      1. Load default vector from yaml (must list every WEIGHT_DIMENSIONS key).
      2. If product != None, partial-override per-product entries.
      3. Validate every dimension present (raise ValueError on miss).
      4. If sum != 1.0 (tol 0.01), warn + auto-normalize so final_score stays 0-10.

    Re-loads from disk on every call — caller is responsible for caching if
    they care about cost. Tests mutate the yaml between calls so we deliberately
    skip lru_cache here.
    """
    cfg = _loader.load_weights_config()

    weights: dict[str, float] = dict(cfg.default)
    if product is not None:
        override = cfg.products.get(product)
        if override is None:
            _LOGGER.warning(
                "weights: product %r not in products map (have: %s) — using default only",
                product,
                sorted(cfg.products.keys()),
            )
        else:
            for k, v in override.items():
                weights[k] = float(v)

    missing = [d for d in WEIGHT_DIMENSIONS if d not in weights]
    if missing:
        raise ValueError(
            f"weights for product={product!r} missing dimensions: {missing}. "
            f"Required: {list(WEIGHT_DIMENSIONS)}"
        )
    extra = [k for k in weights if k not in WEIGHT_DIMENSIONS]
    if extra:
        _LOGGER.warning(
            "weights: unknown dimensions %s — ignoring (not in WEIGHT_DIMENSIONS)",
            extra,
        )
        for k in extra:
            weights.pop(k, None)

    total = sum(weights.values())
    if total <= 0:
        raise ValueError(f"weight sum must be positive, got {total}")
    if abs(total - 1.0) > 0.01:
        _LOGGER.warning(
            "weights for product=%r sum to %.4f != 1.0 — auto-normalizing",
            product,
            total,
        )
        weights = {k: v / total for k, v in weights.items()}

    return weights


def load_tier_rules() -> list[tuple[str, float]]:
    """Return tier thresholds as `[(tier, threshold), ...]` sorted descending.

    Iterating in descending order means the first match wins — `decide_tier`
    walks this list and returns immediately when `final_score >= threshold`.
    """
    cfg = _loader.load_tier_rules_config()
    rules = cfg.tiers

    missing = [t for t in TIER_VALUES if t not in rules]
    if missing:
        raise ValueError(f"tier_rules missing tiers: {missing}")

    sorted_rules = sorted(rules.items(), key=lambda kv: -kv[1])

    # Sanity: descending threshold ordering must match S > A > B > C semantically.
    # If the user inverted them, log loudly so they don't get silent garbage.
    expected_order = list(TIER_VALUES)
    actual_order = [t for t, _ in sorted_rules]
    if actual_order != expected_order:
        _LOGGER.warning(
            "tier_rules order after sort %s differs from canonical %s — "
            "thresholds may be misconfigured",
            actual_order,
            expected_order,
        )

    return sorted_rules


def calc_final_score(
    scores: dict[str, int],
    weights: dict[str, float],
) -> float:
    """Weighted sum of 0-10 scores. Caller pre-validates score range."""
    missing = [d for d in WEIGHT_DIMENSIONS if d not in scores]
    if missing:
        raise ValueError(
            f"scores missing dimensions: {missing}. "
            f"Required: {list(WEIGHT_DIMENSIONS)}"
        )
    return sum(float(scores[d]) * float(weights[d]) for d in WEIGHT_DIMENSIONS)


_TIER_EPSILON = 1e-6


def decide_tier(
    final_score: float,
    rules: list[tuple[str, float]],
) -> Tier:
    """First-match tier walk. Below the lowest threshold → C clamp.

    `final_score >= threshold - epsilon` to absorb auto-normalize float
    drift (e.g. 7 × normalized_weights summing to 6.99999999 instead of 7.0).
    Without this, an "all 7s" candidate that intuitively means A drops to B.
    """
    for tier, threshold in rules:
        if final_score >= threshold - _TIER_EPSILON:
            return tier  # type: ignore[return-value]
    return "C"
