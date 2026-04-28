"""Phase 8 — Target channel (the company itself).

Wraps the pre-Phase-8 single-query Brave search so the multi-channel
registry has a uniform interface. When `primary_lang == "ko"` and
`bilingual_on_ko` is set, blends a translated English query into the pool
just like the legacy `search_node`.
"""
from __future__ import annotations

import logging
from typing import Literal

from src.search.base import Article
from src.search.bilingual import bilingual_news_search
from src.search.brave import BraveSearch

__all__ = ["run_target"]

_LOGGER = logging.getLogger(__name__)


def run_target(
    company: str,
    *,
    client: BraveSearch,
    primary_lang: Literal["en", "ko"],
    days: int,
    cap: int,
    translations_ko_to_en: dict[str, str],
    bilingual_on_ko: bool,
    min_foreign_ratio: float,
) -> tuple[list[Article], dict]:
    use_bilingual = primary_lang == "ko" and bilingual_on_ko
    if use_bilingual:
        articles, sub_meta = bilingual_news_search(
            client,
            company,
            primary_lang=primary_lang,
            translations_ko_to_en=translations_ko_to_en,
            days=days,
            total_count=cap,
            min_foreign_ratio=min_foreign_ratio,
        )
    else:
        articles = client.search(
            company, lang=primary_lang, days=days, kind="news", count=cap
        )
        sub_meta = {"mode": f"monolingual_{primary_lang}"}

    capped = articles[:cap]
    for a in capped:
        a.channel = "target"

    meta = {
        **sub_meta,
        "pool_size": len(articles),
        "returned": len(capped),
    }
    return capped, meta
