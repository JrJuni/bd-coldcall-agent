from datetime import datetime, timezone

import numpy as np
import pytest

from src.rag import embeddings as emb_mod
from src.rag.embeddings import dedup_articles
from src.search.base import Article


def _mk(title: str, body: str = "", *, pub: datetime | None = None) -> Article:
    return Article(
        title=title,
        url=f"https://example.test/{title}",
        snippet="",
        source="example.test",
        lang="en",
        published_at=pub,
        body=body,
    )


def _patch_embed(monkeypatch, matrix: np.ndarray) -> None:
    monkeypatch.setattr(emb_mod, "embed_texts", lambda _texts: matrix)


def test_single_article_passes_through(monkeypatch):
    arts = [_mk("a", "body")]
    _patch_embed(monkeypatch, np.array([[1.0]], dtype=np.float32))
    kept, report = dedup_articles(arts, threshold=0.9, min_articles=0)
    assert len(kept) == 1
    assert report.pairs_merged == 0
    assert arts[0].dedup_group_id == -1


def test_identical_pair_is_merged(monkeypatch):
    a, b = _mk("a", "body"), _mk("b", "body")
    _patch_embed(monkeypatch, np.array([[1.0, 0.0], [1.0, 0.0]], dtype=np.float32))
    kept, report = dedup_articles([a, b], threshold=0.9, min_articles=0)
    assert len(kept) == 1
    assert report.pairs_merged == 1
    assert a.dedup_group_id == b.dedup_group_id
    assert a.dedup_group_id != -1


def test_dissimilar_pair_is_kept(monkeypatch):
    a, b = _mk("a", "body"), _mk("b", "body")
    _patch_embed(monkeypatch, np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32))
    kept, report = dedup_articles([a, b], threshold=0.9, min_articles=0)
    assert len(kept) == 2
    assert report.pairs_merged == 0
    assert a.dedup_group_id == -1
    assert b.dedup_group_id == -1


def test_floor_prevents_over_merging(monkeypatch):
    arts = [_mk(f"a{i}", "same body") for i in range(4)]
    _patch_embed(monkeypatch, np.ones((4, 1), dtype=np.float32))
    kept, report = dedup_articles(arts, threshold=0.9, min_articles=3)
    assert len(kept) == 3
    assert report.stopped_by_floor is True
    assert report.pairs_merged == 1  # stop the moment another merge would drop below floor


def test_representative_picks_longest_body(monkeypatch):
    short = _mk("short", "abc")
    long = _mk("long", "a much longer body that wins representative selection")
    _patch_embed(monkeypatch, np.array([[1.0, 0.0], [1.0, 0.0]], dtype=np.float32))
    kept, _ = dedup_articles([short, long], threshold=0.9, min_articles=0)
    assert kept[0].title == "long"


def test_representative_breaks_tie_by_newer_date(monkeypatch):
    old = _mk("old", "same len", pub=datetime(2025, 1, 1, tzinfo=timezone.utc))
    new = _mk("new", "same len", pub=datetime(2026, 1, 1, tzinfo=timezone.utc))
    _patch_embed(monkeypatch, np.array([[1.0, 0.0], [1.0, 0.0]], dtype=np.float32))
    kept, _ = dedup_articles([old, new], threshold=0.9, min_articles=0)
    assert kept[0].title == "new"


def test_preserves_input_order_for_survivors(monkeypatch):
    a = _mk("first", "unique-a")
    b = _mk("second", "unique-b")
    c = _mk("third", "unique-c")
    _patch_embed(monkeypatch, np.eye(3, dtype=np.float32))
    kept, _ = dedup_articles([a, b, c], threshold=0.9, min_articles=0)
    assert [x.title for x in kept] == ["first", "second", "third"]
