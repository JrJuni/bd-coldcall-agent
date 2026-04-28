"""Phase 8 (B) — Competitor channel.

For each competitor name (direct + adjacent) listed in
`config/competitors.yaml`, run a `bilingual_news_search` query, mark every
returned article with `channel="competitor"` + competitor metadata, and
round-robin-cap the merged result to `cap` items so a single competitor
can't dominate.

Direct vs adjacent is preserved as `weight` (1.0 / 0.6) on the article
metadata so a future ranking layer can prefer direct hits without
re-reading the yaml.
"""
from __future__ import annotations

import logging
from typing import Literal

from src.config.schemas import CompetitorsConfig
from src.search.base import Article
from src.search.bilingual import bilingual_news_search
from src.search.brave import BraveSearch
from src.search.channels.types import CompetitorSpec

__all__ = ["run_competitor", "_specs_from_config"]

_LOGGER = logging.getLogger(__name__)


def _specs_from_config(config: CompetitorsConfig) -> list[CompetitorSpec]:
    """Flatten direct + adjacent into ordered specs (direct first)."""
    return [
        CompetitorSpec(name=n, weight=1.0, relation="direct")
        for n in config.direct
        if n.strip()
    ] + [
        CompetitorSpec(name=n, weight=0.6, relation="adjacent")
        for n in config.adjacent
        if n.strip()
    ]


def run_competitor(
    config: CompetitorsConfig,
    *,
    client: BraveSearch,
    primary_lang: Literal["en", "ko"],
    days: int,
    cap: int,
    translations_ko_to_en: dict[str, str],
    per_competitor_count: int = 5,
    min_foreign_ratio: float = 0.5,
) -> tuple[list[Article], dict]:
    """Run news search for every configured competitor.

    Round-robin merges the per-competitor result lists so direct hits
    are interleaved with adjacent hits — preserves coverage when `cap`
    is small (default 5) and `direct` outweighs `adjacent`.

    A single competitor's fetch failure is logged and skipped — the
    channel returns whatever else succeeded. Total channel failure
    (no specs) yields `[]` + meta with `skipped_empty=True`.
    """
    specs = _specs_from_config(config)
    if not specs:
        _LOGGER.warning("competitor channel: no entries in competitors.yaml")
        return [], {
            "competitors_count": 0,
            "skipped_empty": True,
            "pool_size": 0,
            "returned": 0,
        }

    per_spec_pools: list[tuple[CompetitorSpec, list[Article]]] = []
    errors: list[dict] = []
    for spec in specs:
        try:
            articles, _meta = bilingual_news_search(
                client,
                spec.name,
                primary_lang=primary_lang,
                translations_ko_to_en=translations_ko_to_en,
                days=days,
                total_count=per_competitor_count,
                min_foreign_ratio=min_foreign_ratio,
            )
        except Exception as exc:  # noqa: BLE001 — per-competitor isolation
            _LOGGER.warning("competitor %r fetch failed: %s", spec.name, exc)
            errors.append({"competitor": spec.name, "error": str(exc)})
            articles = []
        per_spec_pools.append((spec, articles))

    # Round-robin merge with URL dedup. Mark channel + metadata.
    merged: list[Article] = []
    seen_urls: set[str] = set()
    indices = [0] * len(per_spec_pools)
    pool_size_total = 0
    while len(merged) < cap:
        progressed = False
        for slot, (spec, pool) in enumerate(per_spec_pools):
            i = indices[slot]
            while i < len(pool):
                a = pool[i]
                i += 1
                if not a.url or a.url in seen_urls:
                    continue
                seen_urls.add(a.url)
                a.channel = "competitor"
                a.metadata["competitor_name"] = spec.name
                a.metadata["competitor_weight"] = spec.weight
                a.metadata["competitor_relation"] = spec.relation
                merged.append(a)
                progressed = True
                break
            indices[slot] = i
            if len(merged) >= cap:
                break
        if not progressed:
            break

    pool_size_total = sum(len(p) for _, p in per_spec_pools)

    meta = {
        "competitors_count": len(specs),
        "pool_size": pool_size_total,
        "returned": len(merged),
        "per_competitor_returned": {
            spec.name: sum(
                1
                for a in merged
                if a.metadata.get("competitor_name") == spec.name
            )
            for spec, _ in per_spec_pools
        },
        "errors": errors,
    }
    return merged, meta
