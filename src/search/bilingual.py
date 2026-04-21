"""Bilingual Brave search — translate Korean query to English, fetch both,
and blend so foreign (English) results meet a minimum ratio.

Translation is a static lookup table (configured in settings.yaml). LLM-based
translation is out of scope for Phase 1; replace translate_ko_to_en if/when
a translator is wired in later phases.
"""

from __future__ import annotations

from .base import Article, Kind
from .brave import BraveSearch

__all__ = ["translate_ko_to_en", "bilingual_news_search"]


def translate_ko_to_en(query: str, table: dict[str, str]) -> str | None:
    """Exact-phrase match first, then word-level substitution.

    Returns None if NO word mapped — callers treat that as "no foreign search
    possible" rather than fire off an untranslated Korean query against an
    English index.
    """
    q = query.strip()
    if not q:
        return None
    if q in table:
        return table[q]

    tokens = q.split()
    out: list[str] = []
    matched = False
    for tok in tokens:
        if tok in table:
            out.append(table[tok])
            matched = True
        else:
            out.append(tok)
    return " ".join(out) if matched else None


def bilingual_news_search(
    client: BraveSearch,
    query: str,
    *,
    primary_lang: str,
    translations_ko_to_en: dict[str, str],
    days: int,
    total_count: int,
    min_foreign_ratio: float = 0.5,
    kind: Kind = "news",
) -> tuple[list[Article], dict]:
    """Run bilingual search and blend.

    Strategy when primary_lang == "ko":
    1. Translate the Korean query to English via the lookup table.
    2. Fetch up to Brave's cap (20) from each language.
    3. Take ceil(total_count * min_foreign_ratio) English results first.
    4. Take the remainder from Korean, but cap Korean so the final ratio stays
       ≥ min_foreign_ratio even if the English pool came up short.
    5. If we still have headroom, top up with extra English (ratio stays fine).

    Non-Korean primary languages skip translation and return a single-lang search.
    """
    if primary_lang != "ko":
        articles = client.search(
            query, lang="en", days=days, kind=kind, count=total_count
        )
        return articles, {"mode": "monolingual_en"}

    ko_query = query
    en_query = translate_ko_to_en(query, translations_ko_to_en)

    pool_cap = min(max(total_count, 20), 20)  # Brave news count max = 20
    en_pool: list[Article] = (
        client.search(en_query, lang="en", days=days, kind=kind, count=pool_cap)
        if en_query
        else []
    )
    ko_pool = client.search(
        ko_query, lang="ko", days=days, kind=kind, count=pool_cap
    )

    seen: set[str] = set()

    def take(pool: list[Article], limit: int) -> list[Article]:
        taken: list[Article] = []
        for a in pool:
            if len(taken) >= limit:
                break
            if a.url in seen or not a.url:
                continue
            seen.add(a.url)
            taken.append(a)
        return taken

    n_en_target = max(int(round(total_count * min_foreign_ratio)), 1)
    n_ko_target = total_count - n_en_target

    en_taken = take(en_pool, n_en_target)

    # Cap ko so ratio stays ≥ min_foreign_ratio even if en is short.
    if min_foreign_ratio > 0 and len(en_taken) > 0:
        ko_max = int(len(en_taken) * (1 - min_foreign_ratio) / min_foreign_ratio)
    else:
        ko_max = n_ko_target
    ko_taken = take(ko_pool, min(n_ko_target, ko_max))

    # Top up remaining slots with extra en (won't hurt ratio).
    shortfall = total_count - len(en_taken) - len(ko_taken)
    if shortfall > 0 and len(en_pool) > len(en_taken):
        en_taken += take(en_pool, shortfall)

    articles = en_taken + ko_taken
    meta = {
        "mode": "bilingual_ko",
        "ko_query": ko_query,
        "en_query": en_query,
        "translation_found": en_query is not None,
        "en_pool_size": len(en_pool),
        "ko_pool_size": len(ko_pool),
        "en_returned": len(en_taken),
        "ko_returned": len(ko_taken),
        "foreign_ratio": (
            len(en_taken) / len(articles) if articles else 0.0
        ),
    }
    return articles, meta
