"""Top-k retrieval API over the persistent vector store.

Module-level singleton keeps Chroma's PersistentClient warm between calls so
repeated retrieves in the same process don't pay the init cost. Returns
`RetrievedChunk` with a `similarity_score` in [0, 1], descending — Phase 4's
synthesis node can assemble the prompt directly without re-querying.

Phase 10 P10-2a: a `namespace` keyword (default `"default"`) routes to a
per-workspace ChromaDB persist directory.

Phase 11 P11-1: a `ws_slug` keyword (default `"default"`) routes to a
per-workspace root, on top of the existing namespace split. The cache is
a dict keyed by (ws_slug, namespace), so the first retrieve in each
(ws, ns) pair pays the load cost once and subsequent calls are warm.
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
from src.rag.workspaces import workspace_paths


DEFAULT_WS_SLUG = "default"


_LOCK = threading.Lock()
_STORES: dict[tuple[str, str], VectorStore] = {}


def _store(
    ws_slug: str = DEFAULT_WS_SLUG,
    namespace: str = DEFAULT_NAMESPACE,
) -> VectorStore:
    key = (ws_slug, namespace)
    cached = _STORES.get(key)
    if cached is not None:
        return cached
    with _LOCK:
        cached = _STORES.get(key)
        if cached is not None:
            return cached
        settings = get_settings()
        vs_root, _cd_root = workspace_paths(ws_slug)
        persist_path = vectorstore_root_for(vs_root, namespace)
        store = VectorStore(
            persist_path=persist_path,
            collection_name=settings.rag.collection_name,
        )
        _STORES[key] = store
        return store


def reset_store_singleton() -> None:
    """Drop the cached stores — test hook only."""
    with _LOCK:
        _STORES.clear()


def retrieve(
    query: str,
    *,
    ws_slug: str = DEFAULT_WS_SLUG,
    namespace: str = DEFAULT_NAMESPACE,
    top_k: Optional[int] = None,
) -> list[RetrievedChunk]:
    if not query or not query.strip():
        return []
    settings = get_settings()
    k = top_k if top_k is not None else settings.rag.top_k
    emb = embed_texts([query])
    return _store(ws_slug, namespace).query(emb, k)
