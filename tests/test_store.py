from datetime import datetime, timezone

import numpy as np
import pytest

from src.rag.store import VectorStore
from src.rag.types import Chunk


def _make_chunk(
    doc_id: str,
    idx: int,
    *,
    text: str = "sample text",
    title: str = "Doc Title",
    source_type: str = "local",
    source_ref: str = "sample.md",
    mime_type: str = "text/markdown",
    last_modified: datetime | None = None,
    extra: dict | None = None,
) -> Chunk:
    return Chunk(
        id=f"{doc_id}::{idx}",
        doc_id=doc_id,
        chunk_index=idx,
        text=text,
        title=title,
        source_type=source_type,
        source_ref=source_ref,
        last_modified=last_modified
        or datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc),
        mime_type=mime_type,
        extra_metadata=extra or {},
    )


def _unit(vec: list[float]) -> np.ndarray:
    a = np.array(vec, dtype=np.float32)
    return a / np.linalg.norm(a)


@pytest.fixture
def store(tmp_path):
    return VectorStore(tmp_path / "vs", "test_collection")


def test_empty_store_count_is_zero(store):
    assert store.count() == 0
    assert store.all_doc_ids() == set()


def test_query_on_empty_store_returns_empty(store):
    q = np.array([[1.0, 0.0, 0.0]], dtype=np.float32)
    assert store.query(q, top_k=5) == []


def test_upsert_and_count(store):
    chunks = [_make_chunk("doc1", 0), _make_chunk("doc1", 1)]
    embs = np.stack([_unit([1.0, 0.0, 0.0]), _unit([0.0, 1.0, 0.0])])
    store.upsert_chunks(chunks, embs)
    assert store.count() == 2


def test_query_returns_most_similar_first(store):
    chunks = [
        _make_chunk("a", 0, text="alpha"),
        _make_chunk("b", 0, text="beta"),
        _make_chunk("c", 0, text="gamma"),
    ]
    # a: aligned with query; b: near-aligned; c: orthogonal
    embs = np.stack(
        [
            _unit([1.0, 0.0, 0.0]),
            _unit([0.9, 0.1, 0.0]),
            _unit([0.0, 1.0, 0.0]),
        ]
    )
    store.upsert_chunks(chunks, embs)

    query = np.array([[1.0, 0.0, 0.0]], dtype=np.float32)
    results = store.query(query, top_k=3)

    assert len(results) == 3
    assert results[0].chunk.id == "a::0"
    scores = [r.similarity_score for r in results]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] > 0.99
    assert 0.0 <= scores[-1] <= 1.0


def test_similarity_score_in_expected_range(store):
    chunks = [_make_chunk("a", 0), _make_chunk("b", 0)]
    embs = np.stack([_unit([1.0, 0.0, 0.0]), _unit([-1.0, 0.0, 0.0])])
    store.upsert_chunks(chunks, embs)

    query = np.array([[1.0, 0.0, 0.0]], dtype=np.float32)
    results = store.query(query, top_k=2)
    scores = {r.chunk.id: r.similarity_score for r in results}
    # identical → ~1.0, opposite → ~0.0
    assert scores["a::0"] > 0.99
    assert scores["b::0"] < 0.01


def test_extra_metadata_round_trip(store):
    nested = {
        "url": "https://example.com/page",
        "tags": ["ai", "enterprise"],
        "page_count": 7,
        "nested": {"level": 2, "flag": True},
    }
    chunk = _make_chunk("doc-x", 0, extra=nested)
    emb = _unit([1.0, 0.0, 0.0]).reshape(1, -1)
    store.upsert_chunks([chunk], emb)

    result = store.query(np.array([[1.0, 0.0, 0.0]]), top_k=1)
    assert len(result) == 1
    assert result[0].chunk.extra_metadata == nested


def test_promoted_fields_round_trip(store):
    ts = datetime(2025, 12, 31, 23, 59, tzinfo=timezone.utc)
    chunk = _make_chunk(
        "doc-p",
        3,
        text="promoted fields check",
        title="Promotion",
        source_type="notion",
        source_ref="notion:page:abc",
        mime_type="text/notion",
        last_modified=ts,
    )
    emb = _unit([1.0, 0.0, 0.0]).reshape(1, -1)
    store.upsert_chunks([chunk], emb)

    result = store.query(np.array([[1.0, 0.0, 0.0]]), top_k=1)
    rc = result[0].chunk
    assert rc.id == "doc-p::3"
    assert rc.doc_id == "doc-p"
    assert rc.chunk_index == 3
    assert rc.title == "Promotion"
    assert rc.source_type == "notion"
    assert rc.source_ref == "notion:page:abc"
    assert rc.mime_type == "text/notion"
    assert rc.text == "promoted fields check"
    assert rc.last_modified == ts


def test_last_modified_none_round_trip(store):
    chunk = _make_chunk("doc-n", 0, last_modified=None)
    # dataclass default fills in, so override manually:
    chunk.last_modified = None
    emb = _unit([1.0, 0.0, 0.0]).reshape(1, -1)
    store.upsert_chunks([chunk], emb)

    result = store.query(np.array([[1.0, 0.0, 0.0]]), top_k=1)
    assert result[0].chunk.last_modified is None


def test_delete_document_removes_all_chunks(store):
    chunks = [
        _make_chunk("doc-keep", 0),
        _make_chunk("doc-del", 0),
        _make_chunk("doc-del", 1),
    ]
    embs = np.stack(
        [
            _unit([1.0, 0.0, 0.0]),
            _unit([0.0, 1.0, 0.0]),
            _unit([0.0, 0.0, 1.0]),
        ]
    )
    store.upsert_chunks(chunks, embs)
    assert store.count() == 3

    store.delete_document("doc-del")
    assert store.count() == 1
    assert store.all_doc_ids() == {"doc-keep"}


def test_upsert_overwrites_existing_id(store):
    chunk_v1 = _make_chunk("doc-u", 0, text="version 1")
    chunk_v2 = _make_chunk("doc-u", 0, text="version 2")
    emb = _unit([1.0, 0.0, 0.0]).reshape(1, -1)

    store.upsert_chunks([chunk_v1], emb)
    assert store.count() == 1
    store.upsert_chunks([chunk_v2], emb)
    assert store.count() == 1

    result = store.query(np.array([[1.0, 0.0, 0.0]]), top_k=1)
    assert result[0].chunk.text == "version 2"


def test_all_doc_ids_deduplicates(store):
    chunks = [
        _make_chunk("doc-a", 0),
        _make_chunk("doc-a", 1),
        _make_chunk("doc-b", 0),
    ]
    embs = np.stack(
        [_unit([1, 0, 0]), _unit([0, 1, 0]), _unit([0, 0, 1])]
    )
    store.upsert_chunks(chunks, embs)
    assert store.all_doc_ids() == {"doc-a", "doc-b"}


def test_empty_upsert_is_noop(store):
    store.upsert_chunks([], np.zeros((0, 3)))
    assert store.count() == 0


def test_upsert_length_mismatch_raises(store):
    chunk = _make_chunk("doc-x", 0)
    embs = np.stack([_unit([1, 0, 0]), _unit([0, 1, 0])])
    with pytest.raises(ValueError):
        store.upsert_chunks([chunk], embs)


def test_top_k_larger_than_count_returns_all(store):
    chunks = [_make_chunk("a", 0), _make_chunk("b", 0)]
    embs = np.stack([_unit([1, 0, 0]), _unit([0, 1, 0])])
    store.upsert_chunks(chunks, embs)

    result = store.query(np.array([[1, 0, 0]]), top_k=10)
    assert len(result) == 2
