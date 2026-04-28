"""Phase 8 Stream 1 — competitor channel."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
import yaml

from src.config.loader import load_competitors
from src.config.schemas import CompetitorsConfig
from src.search.base import Article
from src.search.channels import competitor as competitor_channel
from src.search.channels.types import CompetitorSpec


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
    """Map: query -> list[Article]. Returns empty list for unknown queries."""

    def __init__(self, mapping: dict[str, list[Article]]):
        self._mapping = mapping
        self.calls: list[tuple[str, str, int]] = []

    def search(self, query, *, lang, days, kind="news", count=10):
        self.calls.append((query, lang, count))
        return list(self._mapping.get(query, []))[:count]


def test_specs_from_config_orders_direct_first():
    cfg = CompetitorsConfig(direct=["A", "B"], adjacent=["C"])
    specs = competitor_channel._specs_from_config(cfg)
    assert [s.name for s in specs] == ["A", "B", "C"]
    assert [s.relation for s in specs] == ["direct", "direct", "adjacent"]
    assert [s.weight for s in specs] == [1.0, 1.0, 0.6]


def test_specs_from_config_strips_blanks():
    cfg = CompetitorsConfig(direct=["A", "  "], adjacent=[""])
    specs = competitor_channel._specs_from_config(cfg)
    assert [s.name for s in specs] == ["A"]


def test_run_competitor_empty_config_returns_skipped_meta():
    arts, meta = competitor_channel.run_competitor(
        CompetitorsConfig(),
        client=_StubClient({}),
        primary_lang="en",
        days=30,
        cap=5,
        translations_ko_to_en={},
    )
    assert arts == []
    assert meta["skipped_empty"] is True
    assert meta["competitors_count"] == 0


def test_run_competitor_marks_channel_and_metadata():
    cfg = CompetitorsConfig(direct=["Snowflake"], adjacent=["Cloudera"])
    snow_pool = [_article("https://news.com/snow1"), _article("https://news.com/snow2")]
    cld_pool = [_article("https://news.com/cld1")]
    client = _StubClient({"Snowflake": snow_pool, "Cloudera": cld_pool})

    arts, meta = competitor_channel.run_competitor(
        cfg,
        client=client,
        primary_lang="en",
        days=30,
        cap=10,
        translations_ko_to_en={},
        per_competitor_count=5,
    )

    assert {a.channel for a in arts} == {"competitor"}
    assert all("competitor_name" in a.metadata for a in arts)
    snow = [a for a in arts if a.metadata["competitor_name"] == "Snowflake"]
    cld = [a for a in arts if a.metadata["competitor_name"] == "Cloudera"]
    assert len(snow) == 2 and all(a.metadata["competitor_weight"] == 1.0 for a in snow)
    assert len(cld) == 1 and cld[0].metadata["competitor_weight"] == 0.6
    assert cld[0].metadata["competitor_relation"] == "adjacent"
    assert meta["pool_size"] == 3
    assert meta["returned"] == 3


def test_run_competitor_round_robin_caps():
    """cap=3, two competitors each with 5 hits — should interleave."""
    cfg = CompetitorsConfig(direct=["A", "B"])
    a_pool = [_article(f"https://a.com/{i}") for i in range(5)]
    b_pool = [_article(f"https://b.com/{i}") for i in range(5)]
    client = _StubClient({"A": a_pool, "B": b_pool})

    arts, meta = competitor_channel.run_competitor(
        cfg,
        client=client,
        primary_lang="en",
        days=30,
        cap=3,
        translations_ko_to_en={},
    )

    # Round-robin: A0, B0, A1
    assert [a.url for a in arts] == [
        "https://a.com/0",
        "https://b.com/0",
        "https://a.com/1",
    ]
    assert meta["returned"] == 3


def test_run_competitor_dedup_across_competitors():
    """Same URL surfacing for two competitors is kept only once."""
    cfg = CompetitorsConfig(direct=["A"], adjacent=["B"])
    shared = _article("https://news.com/shared")
    a_pool = [shared, _article("https://news.com/a-only")]
    b_pool = [_article("https://news.com/shared"), _article("https://news.com/b-only")]
    client = _StubClient({"A": a_pool, "B": b_pool})

    arts, _ = competitor_channel.run_competitor(
        cfg,
        client=client,
        primary_lang="en",
        days=30,
        cap=10,
        translations_ko_to_en={},
    )
    urls = [a.url for a in arts]
    assert urls.count("https://news.com/shared") == 1


def test_run_competitor_per_competitor_failure_isolated():
    """If one competitor's search raises, others still return."""
    cfg = CompetitorsConfig(direct=["good", "bad"])
    good_pool = [_article("https://news.com/g")]

    class _PartialFailClient(_StubClient):
        def search(self, query, *, lang, days, kind="news", count=10):
            if query == "bad":
                raise RuntimeError("brave 5xx")
            return super().search(
                query, lang=lang, days=days, kind=kind, count=count
            )

    client = _PartialFailClient({"good": good_pool})

    arts, meta = competitor_channel.run_competitor(
        cfg,
        client=client,
        primary_lang="en",
        days=30,
        cap=5,
        translations_ko_to_en={},
    )
    assert [a.url for a in arts] == ["https://news.com/g"]
    assert len(meta["errors"]) == 1
    assert meta["errors"][0]["competitor"] == "bad"


def test_load_competitors_missing_file_returns_empty(tmp_path):
    cfg = load_competitors(tmp_path / "nonexistent.yaml")
    assert cfg.direct == []
    assert cfg.adjacent == []


def test_load_competitors_reads_yaml(tmp_path):
    p = tmp_path / "competitors.yaml"
    p.write_text(
        yaml.safe_dump({"direct": ["X"], "adjacent": ["Y", "Z"]}),
        encoding="utf-8",
    )
    cfg = load_competitors(p)
    assert cfg.direct == ["X"]
    assert cfg.adjacent == ["Y", "Z"]


def test_load_competitors_empty_yaml(tmp_path):
    p = tmp_path / "competitors.yaml"
    p.write_text("", encoding="utf-8")
    cfg = load_competitors(p)
    assert cfg.direct == []
    assert cfg.adjacent == []
