"""Top-k retrieval API over the persistent vector store.

Module-level singleton keeps Chroma's PersistentClient warm between calls so
repeated retrieves in the same process don't pay the init cost. Returns
`RetrievedChunk` with a `similarity_score` in [0, 1], descending — Phase 4's
synthesis node can assemble the prompt directly without re-querying.

Phase 10 P10-2a: a `namespace` keyword (default `"default"`) routes to a
per-workspace ChromaDB persist directory. The cache is a dict keyed by
namespace, so the first retrieve in each namespace pays the load cost
once and subsequent calls are warm.
"""
from __future__ import annotations

import threading
from typing import Optional

from src.config.loader import get_settings
from src.rag.embeddings import embed_texts
from src.rag.namespace import (
    DEFAULT_NAMESPACE,
    vectorstore_root_for,
)
from src.rag.store import VectorStore
from src.rag.types import RetrievedChunk


_LOCK = threading.Lock()
_STORES: dict[str, VectorStore] = {}


def _store(namespace: str = DEFAULT_NAMESPACE) -> VectorStore:
    cached = _STORES.get(namespace)
    if cached is not None:
        return cached
    with _LOCK:
        cached = _STORES.get(namespace)
        if cached is not None:
            return cached
        settings = get_settings()
        persist_path = vectorstore_root_for(
            settings.rag.vectorstore_path, namespace
        )
        store = VectorStore(
            persist_path=persist_path,
            collection_name=settings.rag.collection_name,
        )
        _STORES[namespace] = store
        return store


def reset_store_singleton() -> None:
    """Drop the cached stores — test hook only."""
    with _LOCK:
        _STORES.clear()


def retrieve(
    query: str,
    *,
    namespace: str = DEFAULT_NAMESPACE,
    top_k: Optional[int] = None,
) -> list[RetrievedChunk]:
    if not query or not query.strip():
        return []
    settings = get_settings()
    k = top_k if top_k is not None else settings.rag.top_k
    emb = embed_texts([query])
    return _store(namespace).query(emb, k)
