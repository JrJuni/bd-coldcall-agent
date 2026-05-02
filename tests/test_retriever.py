from datetime import datetime, timezone

import numpy as np
import pytest

from src.rag import retriever as retriever_mod
from src.rag.store import VectorStore
from src.rag.types import Chunk


def _unit(vec):
    a = np.array(vec, dtype=np.float32)
    return a / np.linalg.norm(a)


def _chunk(doc_id: str, idx: int, text: str) -> Chunk:
    return Chunk(
        id=f"{doc_id}::{idx}",
        doc_id=doc_id,
        chunk_index=idx,
        text=text,
        title=f"Title {doc_id}",
        source_type="local",
        source_ref=f"{doc_id}.md",
        last_modified=datetime(2026, 4, 20, tzinfo=timezone.utc),
        mime_type="text/markdown",
        extra_metadata={"size_bytes": 100 + idx},
    )


@pytest.fixture
def patched_store(tmp_path, monkeypatch):
    """A VectorStore pre-populated with three chunks + deterministic embeddings.

    Patches retriever._store() to return this store, and embed_texts() to
    return the query embedding we control per-test.
    """
    store = VectorStore(tmp_path / "vs", "test_retriever")
    chunks = [
        _chunk("a", 0, "alpha content"),
        _chunk("b", 0, "beta content"),
        _chunk("c", 0, "gamma content"),
    ]
    embs = np.stack(
        [
            _unit([1.0, 0.0, 0.0]),  # a
            _unit([0.9, 0.1, 0.0]),  # b (near a)
            _unit([0.0, 1.0, 0.0]),  # c (orthogonal)
        ]
    )
    store.upsert_chunks(chunks, embs)

    retriever_mod.reset_store_singleton()
    monkeypatch.setattr(
        retriever_mod,
        "_store",
        lambda ws_slug="default", namespace="default": store,
    )

    # Default query-embedding stub: caller can override via monkeypatch
    def fake_embed(texts):
        return np.array([[1.0, 0.0, 0.0]], dtype=np.float32)

    monkeypatch.setattr(retriever_mod, "embed_texts", fake_embed)
    yield store
    retriever_mod.reset_store_singleton()


def test_retrieve_returns_descending_similarity(patched_store):
    results = retriever_mod.retrieve("anything", top_k=3)
    assert len(results) == 3
    scores = [r.similarity_score for r in results]
    assert scores == sorted(scores, reverse=True)
    assert results[0].chunk.id == "a::0"


def test_retrieve_top_k_limits_results(patched_store):
    results = retriever_mod.retrieve("anything", top_k=2)
    assert len(results) == 2


def test_retrieve_default_top_k_from_settings(patched_store, monkeypatch):
    from src.rag import retriever as rmod

    class FakeRAG:
        top_k = 1

    class FakeSettings:
        rag = FakeRAG()

    monkeypatch.setattr(rmod, "get_settings", lambda: FakeSettings())
    results = rmod.retrieve("anything")
    assert len(results) == 1


def test_retrieve_empty_query_returns_empty(patched_store):
    assert retriever_mod.retrieve("") == []
    assert retriever_mod.retrieve("   ") == []


def test_retrieved_chunk_has_full_fields(patched_store):
    results = retriever_mod.retrieve("anything", top_k=1)
    rc = results[0]
    assert 0.0 <= rc.similarity_score <= 1.0
    chunk = rc.chunk
    assert chunk.id == "a::0"
    assert chunk.doc_id == "a"
    assert chunk.chunk_index == 0
    assert chunk.title == "Title a"
    assert chunk.source_type == "local"
    assert chunk.source_ref == "a.md"
    assert chunk.mime_type == "text/markdown"
    assert chunk.text == "alpha content"
    assert chunk.last_modified == datetime(2026, 4, 20, tzinfo=timezone.utc)
    assert chunk.extra_metadata == {"size_bytes": 100}


def test_retrieve_query_embedding_changes_ordering(patched_store, monkeypatch):
    # Switch the query direction toward chunk 'c' (orthogonal axis)
    monkeypatch.setattr(
        retriever_mod,
        "embed_texts",
        lambda texts: np.array([[0.0, 1.0, 0.0]], dtype=np.float32),
    )
    results = retriever_mod.retrieve("something", top_k=3)
    assert results[0].chunk.id == "c::0"
