"""Phase 8 Stream 2 — related channel."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
import yaml

from src.config.loader import load_intent_tiers
from src.config.schemas import IntentTierEntry, IntentTiersConfig
from src.search.base import Article
from src.search.channels import related as related_channel
from src.search.channels.types import IntentSpec


def _article(url: str, lang: str = "en") -> Article:
    return Article(
        title=f"T-{url}",
        url=url,
        snippet="snip",
        source="src",
        lang=lang,
        published_at=datetime(2026, 4, 20),
    )


class _StubClient:
    """Map: query -> list[Article]."""

    def __init__(self, mapping: dict[str, list[Article]]):
        self._mapping = mapping
        self.calls: list[tuple[str, str, int]] = []

    def search(self, query, *, lang, days, kind="news", count=10):
        self.calls.append((query, lang, count))
        return list(self._mapping.get(query, []))[:count]


def _spec(label: str, tier: str, kw_en: tuple = ("kw",)) -> IntentSpec:
    return IntentSpec(label=label, tier=tier, keywords_en=kw_en)


def test_allocate_slots_proportional_to_tier_weight():
    specs = [
        _spec("a", "S"),
        _spec("b", "A"),
        _spec("c", "B"),
        _spec("d", "C"),
    ]
    alloc = related_channel.allocate_slots(specs, cap=15)
    # weights 5/4/3/2 → 14 base, +1 remainder to S
    assert alloc == {"a": 6, "b": 4, "c": 3, "d": 2}
    assert sum(alloc.values()) == 15


def test_allocate_slots_zero_cap_returns_zeros_or_empty():
    specs = [_spec("a", "S")]
    alloc = related_channel.allocate_slots(specs, cap=0)
    assert alloc == {}


def test_allocate_slots_remainder_breaks_ties_by_yaml_order():
    """Two S-tier specs, cap=11 → 5+5 base, remainder 1 → first by order."""
    specs = [_spec("a", "S"), _spec("b", "S")]
    alloc = related_channel.allocate_slots(specs, cap=11)
    assert alloc["a"] == 6 and alloc["b"] == 5


def test_run_related_empty_config_skipped():
    arts, meta = related_channel.run_related(
        IntentTiersConfig(),
        company="X",
        client=_StubClient({}),
        primary_lang="en",
        days=30,
        cap=15,
        translations_ko_to_en={},
    )
    assert arts == []
    assert meta["skipped_empty"] is True


def test_run_related_marks_metadata_and_channel():
    cfg = IntentTiersConfig(
        intents=[
            IntentTierEntry(
                label="lakehouse_modernization",
                tier="S",
                keywords_en=["lakehouse"],
            )
        ]
    )
    pool = [_article("https://news.com/a"), _article("https://news.com/b")]
    client = _StubClient({"NVIDIA lakehouse": pool})

    arts, meta = related_channel.run_related(
        cfg,
        company="NVIDIA",
        client=client,
        primary_lang="en",
        days=30,
        cap=15,
        translations_ko_to_en={},
    )

    assert {a.channel for a in arts} == {"related"}
    assert all(a.metadata["intent_label"] == "lakehouse_modernization" for a in arts)
    assert all(a.metadata["intent_tier"] == "S" for a in arts)
    assert all(a.metadata["intent_query"] == "NVIDIA lakehouse" for a in arts)
    assert meta["returned"] == 2
    assert meta["allocations"]["lakehouse_modernization"] == 15


def test_run_related_dedup_across_intents():
    """Same URL surfacing for two intents — first intent in yaml order keeps."""
    cfg = IntentTiersConfig(
        intents=[
            IntentTierEntry(label="i1", tier="S", keywords_en=["alpha"]),
            IntentTierEntry(label="i2", tier="A", keywords_en=["beta"]),
        ]
    )
    shared = _article("https://news.com/shared")
    p1 = [shared]
    p2 = [_article("https://news.com/shared"), _article("https://news.com/b")]
    client = _StubClient({"X alpha": p1, "X beta": p2})

    arts, _ = related_channel.run_related(
        cfg,
        company="X",
        client=client,
        primary_lang="en",
        days=30,
        cap=15,
        translations_ko_to_en={},
    )
    urls = [a.url for a in arts]
    assert urls.count("https://news.com/shared") == 1
    # First-intent wins → /shared is tagged i1
    shared_art = next(a for a in arts if a.url == "https://news.com/shared")
    assert shared_art.metadata["intent_label"] == "i1"


def test_run_related_intent_with_no_keywords_skipped():
    cfg = IntentTiersConfig(
        intents=[
            IntentTierEntry(label="empty_kw", tier="S"),
            IntentTierEntry(label="has_kw", tier="A", keywords_en=["beta"]),
        ]
    )
    client = _StubClient({"X beta": [_article("https://news.com/b")]})

    arts, meta = related_channel.run_related(
        cfg,
        company="X",
        client=client,
        primary_lang="en",
        days=30,
        cap=15,
        translations_ko_to_en={},
    )
    assert [a.url for a in arts] == ["https://news.com/b"]
    assert meta["per_intent_returned"]["empty_kw"] == 0


def test_run_related_per_intent_failure_isolated():
    cfg = IntentTiersConfig(
        intents=[
            IntentTierEntry(label="bad", tier="S", keywords_en=["broken"]),
            IntentTierEntry(label="good", tier="A", keywords_en=["fine"]),
        ]
    )

    class _PartialClient(_StubClient):
        def search(self, query, *, lang, days, kind="news", count=10):
            if "broken" in query:
                raise RuntimeError("brave 5xx")
            return super().search(
                query, lang=lang, days=days, kind=kind, count=count
            )

    client = _PartialClient({"X fine": [_article("https://news.com/g")]})

    arts, meta = related_channel.run_related(
        cfg,
        company="X",
        client=client,
        primary_lang="en",
        days=30,
        cap=15,
        translations_ko_to_en={},
    )
    assert [a.url for a in arts] == ["https://news.com/g"]
    assert any(e["intent"] == "bad" for e in meta["errors"])


def test_run_related_picks_korean_keyword_when_lang_ko():
    cfg = IntentTiersConfig(
        intents=[
            IntentTierEntry(
                label="i1",
                tier="S",
                keywords_en=["english"],
                keywords_ko=["한국어"],
            )
        ]
    )
    client = _StubClient({"엔비디아 한국어": [_article("https://k.com/a", "ko")]})

    arts, _ = related_channel.run_related(
        cfg,
        company="엔비디아",
        client=client,
        primary_lang="ko",
        days=30,
        cap=15,
        translations_ko_to_en={},
    )
    assert [a.url for a in arts] == ["https://k.com/a"]


def test_load_intent_tiers_missing_file_returns_empty(tmp_path):
    cfg = load_intent_tiers(tmp_path / "nope.yaml")
    assert cfg.intents == []


def test_load_intent_tiers_reads_yaml(tmp_path):
    p = tmp_path / "intent_tiers.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "intents": [
                    {
                        "label": "x",
                        "tier": "S",
                        "description": "desc",
                        "keywords_en": ["e1"],
                        "keywords_ko": ["k1"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    cfg = load_intent_tiers(p)
    assert cfg.intents[0].label == "x"
    assert cfg.intents[0].tier == "S"
    assert cfg.intents[0].keywords_en == ["e1"]
