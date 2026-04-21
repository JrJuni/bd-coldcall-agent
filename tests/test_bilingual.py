from datetime import datetime

import pytest

from src.search.base import Article
from src.search.bilingual import bilingual_news_search, translate_ko_to_en


TABLE = {
    "AI 산업": "AI industry",
    "반도체": "semiconductor",
    "산업": "industry",
}


def test_translate_exact_phrase_wins():
    assert translate_ko_to_en("AI 산업", TABLE) == "AI industry"


def test_translate_word_level_fallback():
    # "반도체 산업" has no exact entry but both words map
    assert translate_ko_to_en("반도체 산업", TABLE) == "semiconductor industry"


def test_translate_no_match_returns_none():
    assert translate_ko_to_en("완전히 다른 문구", TABLE) is None


def test_translate_empty_returns_none():
    assert translate_ko_to_en("   ", TABLE) is None


def _a(url: str, lang: str) -> Article:
    return Article(
        title=f"T-{url}",
        url=url,
        snippet="",
        source=url.split("/")[-2] if "/" in url else "src",
        lang=lang,
        published_at=datetime(2026, 4, 20),
    )


class _StubClient:
    """Drop-in for BraveSearch that serves pre-baked pools by language."""

    def __init__(self, en_pool, ko_pool):
        self._pools = {"en": en_pool, "ko": ko_pool}
        self.calls: list[tuple] = []

    def search(self, query, *, lang, days, kind="news", count=10):
        self.calls.append((query, lang, count))
        return list(self._pools.get(lang, []))[:count]


def test_bilingual_enforces_fifty_percent_when_both_pools_abundant():
    en_pool = [_a(f"https://e.com/{i}", "en") for i in range(20)]
    ko_pool = [_a(f"https://k.com/{i}", "ko") for i in range(20)]
    stub = _StubClient(en_pool, ko_pool)

    articles, meta = bilingual_news_search(
        stub,
        "AI 산업",
        primary_lang="ko",
        translations_ko_to_en=TABLE,
        days=30,
        total_count=20,
        min_foreign_ratio=0.5,
    )

    assert len(articles) == 20
    en_count = sum(1 for a in articles if a.lang == "en")
    assert en_count / len(articles) >= 0.5
    assert meta["translation_found"] is True
    assert meta["en_query"] == "AI industry"


def test_bilingual_keeps_ratio_when_en_pool_short():
    # Only 4 English available; with min_foreign_ratio 0.5 we cap ko at 4.
    en_pool = [_a(f"https://e.com/{i}", "en") for i in range(4)]
    ko_pool = [_a(f"https://k.com/{i}", "ko") for i in range(20)]
    stub = _StubClient(en_pool, ko_pool)

    articles, meta = bilingual_news_search(
        stub,
        "AI 산업",
        primary_lang="ko",
        translations_ko_to_en=TABLE,
        days=30,
        total_count=20,
        min_foreign_ratio=0.5,
    )

    # Can't hit 20 without breaking the ratio; must still be ≥ 50% en.
    assert len(articles) <= 20
    en_count = sum(1 for a in articles if a.lang == "en")
    if articles:
        assert en_count / len(articles) >= 0.5
    assert meta["en_returned"] == 4


def test_bilingual_skips_en_when_translation_missing():
    en_pool = [_a(f"https://e.com/{i}", "en") for i in range(5)]
    ko_pool = [_a(f"https://k.com/{i}", "ko") for i in range(10)]
    stub = _StubClient(en_pool, ko_pool)

    articles, meta = bilingual_news_search(
        stub,
        "번역불가쿼리",
        primary_lang="ko",
        translations_ko_to_en=TABLE,
        days=30,
        total_count=10,
        min_foreign_ratio=0.5,
    )

    assert meta["translation_found"] is False
    assert meta["en_pool_size"] == 0
    # Did not invoke English search at all
    assert not any(call[1] == "en" for call in stub.calls)


def test_bilingual_deduplicates_by_url():
    shared = _a("https://shared.com/1", "en")
    en_pool = [shared, _a("https://e.com/2", "en")]
    ko_pool = [shared, _a("https://k.com/3", "ko")]
    stub = _StubClient(en_pool, ko_pool)

    articles, _meta = bilingual_news_search(
        stub,
        "AI 산업",
        primary_lang="ko",
        translations_ko_to_en=TABLE,
        days=30,
        total_count=10,
        min_foreign_ratio=0.5,
    )
    urls = [a.url for a in articles]
    assert len(urls) == len(set(urls))


def test_non_ko_primary_bypasses_bilingual():
    en_pool = [_a(f"https://e.com/{i}", "en") for i in range(5)]
    stub = _StubClient(en_pool, [])
    articles, meta = bilingual_news_search(
        stub,
        "AI industry",
        primary_lang="en",
        translations_ko_to_en=TABLE,
        days=30,
        total_count=5,
        min_foreign_ratio=0.5,
    )
    assert meta["mode"] == "monolingual_en"
    assert len(articles) == 5
