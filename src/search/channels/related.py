"""Phase 8 (A) — Related channel.

Static intent tiers (`config/intent_tiers.yaml`) drive query generation.
Each entry contributes 1+ Brave queries `f"{company} {keyword}"` weighted
by tier — the channel cap (default 15) is split proportionally so S-tier
intents get the most slots.

The intent tiers themselves are produced offline by
`scripts/draft_intent_tiers.py` (one Sonnet call seeded by the RAG index)
and then hand-edited; the runtime path is purely deterministic, no LLM.
"""
from __future__ import annotations

import logging
from typing import Literal

from src.config.schemas import IntentTierEntry, IntentTiersConfig
from src.search.base import Article
from src.search.bilingual import bilingual_news_search
from src.search.brave import BraveSearch
from src.search.channels.types import IntentSpec, Tier

__all__ = [
    "TIER_WEIGHTS",
    "allocate_slots",
    "run_related",
    "_specs_from_config",
]

_LOGGER = logging.getLogger(__name__)

TIER_WEIGHTS: dict[Tier, int] = {"S": 5, "A": 4, "B": 3, "C": 2}


def _specs_from_config(config: IntentTiersConfig) -> list[IntentSpec]:
    out: list[IntentSpec] = []
    for entry in config.intents:
        if not entry.label.strip():
            continue
        out.append(
            IntentSpec(
                label=entry.label,
                tier=entry.tier,
                description=entry.description,
                keywords_ko=tuple(k for k in entry.keywords_ko if k.strip()),
                keywords_en=tuple(k for k in entry.keywords_en if k.strip()),
            )
        )
    return out


def allocate_slots(specs: list[IntentSpec], cap: int) -> dict[str, int]:
    """Distribute `cap` slots across specs by tier weight.

    Floor-then-distribute-remainder algorithm: floor each spec's
    proportional share, then hand the leftover slots out one at a time
    to the highest-weight specs (ties broken by yaml order). Guarantees
    `sum(allocations) == cap` when `len(specs) > 0`.
    """
    if not specs or cap <= 0:
        return {}
    weights = [TIER_WEIGHTS[s.tier] for s in specs]
    total = sum(weights)
    if total == 0:
        return {s.label: 0 for s in specs}

    raw = [cap * w / total for w in weights]
    floored = [int(x) for x in raw]
    remainder = cap - sum(floored)
    # Distribute remainder to highest-weight specs (stable by index).
    order = sorted(range(len(specs)), key=lambda i: (-weights[i], i))
    for i in order[:remainder]:
        floored[i] += 1
    return {specs[i].label: floored[i] for i in range(len(specs))}


def _pick_keyword(spec: IntentSpec, primary_lang: str) -> str | None:
    """First non-empty keyword in the primary language; fall back to the
    other language if empty."""
    if primary_lang == "ko" and spec.keywords_ko:
        return spec.keywords_ko[0]
    if primary_lang == "en" and spec.keywords_en:
        return spec.keywords_en[0]
    if spec.keywords_en:
        return spec.keywords_en[0]
    if spec.keywords_ko:
        return spec.keywords_ko[0]
    return None


def run_related(
    config: IntentTiersConfig,
    *,
    company: str,
    client: BraveSearch,
    primary_lang: Literal["en", "ko"],
    days: int,
    cap: int,
    translations_ko_to_en: dict[str, str],
    min_foreign_ratio: float = 0.5,
) -> tuple[list[Article], dict]:
    """Generate intent-weighted news for our-product ↔ company match.

    Each intent gets `allocate_slots()` slots; the keyword is joined to
    the company name as the Brave query. Results are URL-deduped across
    intents; the first intent to surface a URL wins (so S-tier output
    doesn't lose ranking to a lower-tier reprint).
    """
    specs = _specs_from_config(config)
    if not specs:
        _LOGGER.warning(
            "related channel: no entries in intent_tiers.yaml — "
            "run scripts/draft_intent_tiers.py to seed"
        )
        return [], {
            "intents_count": 0,
            "skipped_empty": True,
            "pool_size": 0,
            "returned": 0,
        }

    allocations = allocate_slots(specs, cap)
    merged: list[Article] = []
    seen_urls: set[str] = set()
    per_intent_returned: dict[str, int] = {}
    errors: list[dict] = []

    for spec in specs:
        slots = allocations.get(spec.label, 0)
        if slots <= 0:
            per_intent_returned[spec.label] = 0
            continue
        keyword = _pick_keyword(spec, primary_lang)
        if not keyword:
            _LOGGER.warning(
                "related channel: intent %r has no keywords in either lang", spec.label
            )
            per_intent_returned[spec.label] = 0
            continue
        query = f"{company} {keyword}".strip()
        try:
            articles, _meta = bilingual_news_search(
                client,
                query,
                primary_lang=primary_lang,
                translations_ko_to_en=translations_ko_to_en,
                days=days,
                total_count=max(slots, 1),
                min_foreign_ratio=min_foreign_ratio,
            )
        except Exception as exc:  # noqa: BLE001 — per-intent isolation
            _LOGGER.warning("related intent %r fetch failed: %s", spec.label, exc)
            errors.append({"intent": spec.label, "error": str(exc)})
            per_intent_returned[spec.label] = 0
            continue

        kept = 0
        for a in articles:
            if kept >= slots:
                break
            if not a.url or a.url in seen_urls:
                continue
            seen_urls.add(a.url)
            a.channel = "related"
            a.metadata["intent_label"] = spec.label
            a.metadata["intent_tier"] = spec.tier
            a.metadata["intent_query"] = query
            merged.append(a)
            kept += 1
        per_intent_returned[spec.label] = kept

    meta = {
        "intents_count": len(specs),
        "allocations": allocations,
        "pool_size": sum(per_intent_returned.values()),  # post-dedup count
        "returned": len(merged),
        "per_intent_returned": per_intent_returned,
        "errors": errors,
    }
    return merged, meta
