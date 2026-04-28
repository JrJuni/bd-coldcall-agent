"""Phase 8 — multi-channel search registry + ThreadPool fan-out.

`run_all_channels` is the single entry point invoked by `search_node`.
It loads channel-specific config (intent_tiers.yaml, competitors.yaml),
fans the three channels out across a ThreadPoolExecutor, and merges the
results with cross-channel URL dedup (channel rank: target > related >
competitor).

Per-channel failure is isolated — the channel returns [] + an error in
the meta. The node only fails if *every* channel raises.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from src.config import loader as _config_loader
from src.config.schemas import Settings
from src.search.base import Article
from src.search.brave import BraveSearch
from src.search.channels.competitor import run_competitor
from src.search.channels.related import run_related
from src.search.channels.target import run_target
from src.search.channels.types import CompetitorSpec, IntentSpec, Tier

__all__ = [
    "CHANNEL_RANK",
    "CompetitorSpec",
    "IntentSpec",
    "Tier",
    "run_all_channels",
]

_LOGGER = logging.getLogger(__name__)

# Lower = higher priority. Used by cross-channel dedup keep-policy.
CHANNEL_RANK: dict[str, int] = {"target": 0, "related": 1, "competitor": 2}


def _per_channel_cap(settings: Settings, channel: str, default: int) -> int:
    return int(settings.search.max_articles_per_channel.get(channel, default))


def run_all_channels(
    *,
    company: str,
    primary_lang: Literal["en", "ko"],
    settings: Settings,
    brave_api_key: str,
    max_workers: int = 3,
) -> tuple[list[Article], dict]:
    """Fan-out across target/related/competitor channels.

    Returns (merged_articles, search_meta). `search_meta["by_channel"]`
    holds each channel's own meta dict; `channel_errors` collects any
    channel-level exceptions; `total_after_xchannel_dedup` is the final
    merged count.
    """
    intent_tiers = _config_loader.load_intent_tiers()
    competitors = _config_loader.load_competitors()

    target_cap = _per_channel_cap(settings, "target", 20)
    related_cap = _per_channel_cap(settings, "related", 15)
    competitor_cap = _per_channel_cap(settings, "competitor", 5)

    results: dict[str, tuple[list[Article], dict]] = {}
    channel_errors: dict[str, str] = {}

    with BraveSearch(brave_api_key) as client:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {
                "target": ex.submit(
                    run_target,
                    company,
                    client=client,
                    primary_lang=primary_lang,
                    days=settings.search.days,
                    cap=target_cap,
                    translations_ko_to_en=settings.search.translations_ko_to_en,
                    bilingual_on_ko=settings.search.bilingual_on_ko,
                    min_foreign_ratio=settings.search.min_foreign_ratio,
                ),
                "related": ex.submit(
                    run_related,
                    intent_tiers,
                    company=company,
                    client=client,
                    primary_lang=primary_lang,
                    days=settings.search.days,
                    cap=related_cap,
                    translations_ko_to_en=settings.search.translations_ko_to_en,
                    min_foreign_ratio=settings.search.min_foreign_ratio,
                ),
                "competitor": ex.submit(
                    run_competitor,
                    competitors,
                    client=client,
                    primary_lang=primary_lang,
                    days=settings.search.days,
                    cap=competitor_cap,
                    translations_ko_to_en=settings.search.translations_ko_to_en,
                ),
            }
            for name, fut in futures.items():
                try:
                    arts, meta = fut.result()
                    results[name] = (arts, meta)
                except Exception as exc:  # noqa: BLE001 — per-channel isolation
                    _LOGGER.warning("channel %s failed: %s", name, exc)
                    channel_errors[name] = str(exc)
                    results[name] = ([], {"error": str(exc), "returned": 0})

    # Cross-channel dedup. Iterate by rank order (target → related →
    # competitor) and keep the first occurrence of each URL.
    merged: list[Article] = []
    seen_urls: set[str] = set()
    for name in sorted(results.keys(), key=lambda k: CHANNEL_RANK.get(k, 99)):
        arts, _meta = results[name]
        for a in arts:
            if not a.url or a.url in seen_urls:
                continue
            seen_urls.add(a.url)
            merged.append(a)

    search_meta = {
        "by_channel": {name: meta for name, (_arts, meta) in results.items()},
        "channel_errors": channel_errors,
        "total_after_xchannel_dedup": len(merged),
    }
    return merged, search_meta
