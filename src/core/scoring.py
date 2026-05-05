"""Phase 9.1 — Discovery scoring engine.

LLM emits 0-10 integer scores per dimension; this module decides the final
score and tier deterministically. The split lets weights / thresholds live in
external yaml so re-running with different weights costs $0 — no Sonnet call,
no re-prompting, just `for c in candidates: c.final_score = ...; c.tier = ...`.

Phase 12: dimensions themselves are yaml-driven. `config/weights.yaml` may
declare a top-level `dimensions:` list (`{key, label, description}` triples);
the legacy 6-dimension hardcoded set under `_FALLBACK_DIMENSIONS` is used
only when the yaml omits the block (legacy Phase 9.1 layout).

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
from src.config.schemas import Dimension


_LOGGER = logging.getLogger(__name__)


# Phase 9.1 hardcoded set — used as fallback when weights.yaml lacks a
# `dimensions:` block. Production yamls should declare their own dimensions
# block; this is purely a back-compat anchor.
_FALLBACK_DIMENSIONS: tuple[Dimension, ...] = (
    Dimension(
        key="pain_severity",
        label="Pain severity",
        description=(
            "How acutely the buyer feels the data/AI problem our product "
            "addresses (high = urgent, low = nice-to-have)."
        ),
    ),
    Dimension(
        key="data_complexity",
        label="Data complexity",
        description="Scale, real-time-ness, structured/unstructured data mix.",
    ),
    Dimension(
        key="governance_need",
        label="Governance need",
        description=(
            "Regulatory, security, access control, lineage requirements."
        ),
    ),
    Dimension(
        key="ai_maturity",
        label="AI maturity",
        description=(
            "Existing AI/ML team and active production workloads "
            "(high = ready to buy, low = still exploring)."
        ),
    ),
    Dimension(
        key="buying_trigger",
        label="Buying trigger",
        description=(
            'Recent investment, reorg, product launch, cost-cut pressure '
            '("why now").'
        ),
    ),
    Dimension(
        key="displacement_ease",
        label="Displacement ease",
        description=(
            "Ease of breaking incumbent solution / internal-build lock-in "
            "(low for hyperscaler core ops, direct competitors)."
        ),
    ),
)


Tier = Literal["S", "A", "B", "C"]
TIER_VALUES: tuple[str, ...] = ("S", "A", "B", "C")


def load_dimensions() -> list[Dimension]:
    """Return the active dimension list.

    Reads `config/weights.yaml::dimensions`. If the block is absent (legacy
    Phase 9.1 layout) returns the hardcoded six-dimension fallback so old
    yamls keep working until they're migrated.

    Re-loads from disk on every call — caller is responsible for caching if
    they care about cost.
    """
    cfg = _loader.load_weights_config()
    if cfg.dimensions:
        return list(cfg.dimensions)
    return list(_FALLBACK_DIMENSIONS)


def get_dimension_keys() -> tuple[str, ...]:
    """Convenience: just the keys, in declaration order."""
    return tuple(d.key for d in load_dimensions())


def __getattr__(name: str):
    """Module-level back-compat shim for the legacy `WEIGHT_DIMENSIONS` constant.

    PEP 562 — `__getattr__` runs once per attribute *access*, so a caller
    doing `from src.core.scoring import WEIGHT_DIMENSIONS` snapshots the
    tuple at import time. It's NOT a live view: rebinding the yaml loader
    *after* the import has happened won't update the bound name.

    New code should call `get_dimension_keys()` directly when it needs the
    current dimension list. This shim exists purely so old imports
    (tests, downstream tooling) keep type-checking and resolving without
    a manual rewrite during the Phase 12 → B4b transition. Plan to remove
    once frontend + recompute snapshot policy land.
    """
    if name == "WEIGHT_DIMENSIONS":
        return get_dimension_keys()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def load_weights(product: str | None = None) -> dict[str, float]:
    """Resolve effective weight vector for `product`.

    Steps:
      1. Load default vector from yaml (must list every dimension key).
      2. If product != None, partial-override per-product entries.
      3. Validate every dimension present (raise ValueError on miss).
      4. If sum != 1.0 (tol 0.01), warn + auto-normalize so final_score stays 0-10.

    Re-loads from disk on every call — caller is responsible for caching if
    they care about cost. Tests mutate the yaml between calls so we deliberately
    skip lru_cache here.
    """
    cfg = _loader.load_weights_config()
    dim_keys = tuple(d.key for d in cfg.dimensions) if cfg.dimensions else tuple(
        d.key for d in _FALLBACK_DIMENSIONS
    )

    weights: dict[str, float] = dict(cfg.default)
    if product is not None:
        profile = cfg.products.get(product)
        if profile is None:
            _LOGGER.warning(
                "weights: product %r not in products map (have: %s) — using default only",
                product,
                sorted(cfg.products.keys()),
            )
        else:
            for k, v in profile.weights.items():
                weights[k] = float(v)

    missing = [d for d in dim_keys if d not in weights]
    if missing:
        raise ValueError(
            f"weights for product={product!r} missing dimensions: {missing}. "
            f"Required: {list(dim_keys)}"
        )
    extra = [k for k in weights if k not in dim_keys]
    if extra:
        _LOGGER.warning(
            "weights: unknown dimensions %s — ignoring (not in declared dimensions %s)",
            extra,
            list(dim_keys),
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
    dim_keys = get_dimension_keys()
    missing = [d for d in dim_keys if d not in scores]
    if missing:
        raise ValueError(
            f"scores missing dimensions: {missing}. "
            f"Required: {list(dim_keys)}"
        )
    return sum(float(scores[d]) * float(weights[d]) for d in dim_keys)


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
