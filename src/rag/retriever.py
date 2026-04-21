"""Top-k retrieval API over the persistent vector store.

Module-level singleton keeps Chroma's PersistentClient warm between calls so
repeated retrieves in the same process don't pay the init cost. Returns
`RetrievedChunk` with a `similarity_score` in [0, 1], descending — Phase 4's
synthesis node can assemble the prompt directly without re-querying.
"""
from __future__ import annotations

import threading
from typing import Optional

from src.config.loader import get_settings
from src.rag.embeddings import embed_texts
from src.rag.store import VectorStore
from src.rag.types import RetrievedChunk


_LOCK = threading.Lock()
_STORE: VectorStore | None = None


def _store() -> VectorStore:
    global _STORE
    if _STORE is not None:
        return _STORE
    with _LOCK:
        if _STORE is not None:
            return _STORE
        settings = get_settings()
        _STORE = VectorStore(
            persist_path=settings.rag.vectorstore_path,
            collection_name=settings.rag.collection_name,
        )
        return _STORE


def reset_store_singleton() -> None:
    """Drop the cached store — test hook only."""
    global _STORE
    with _LOCK:
        _STORE = None


def retrieve(query: str, *, top_k: Optional[int] = None) -> list[RetrievedChunk]:
    if not query or not query.strip():
        return []
    settings = get_settings()
    k = top_k if top_k is not None else settings.rag.top_k
    emb = embed_texts([query])
    return _store().query(emb, k)
