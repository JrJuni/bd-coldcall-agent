"""ChromaDB persistent-store wrapper.

All Chunk metadata is flattened to primitive Chroma keys; the free-form
`extra_metadata` dict is JSON-serialized into a single `extra_json` string so
it round-trips without losing nested structure. Query results come back as
`RetrievedChunk` with `similarity_score` (0-1, higher = more similar) so
callers never see Chroma's raw cosine distance.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from src.rag.types import Chunk, RetrievedChunk


def _iso(dt: datetime | None) -> str:
    return dt.isoformat() if dt is not None else ""


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _flatten(chunk: Chunk) -> dict[str, Any]:
    return {
        "doc_id": chunk.doc_id,
        "chunk_index": chunk.chunk_index,
        "title": chunk.title,
        "source_type": chunk.source_type,
        "source_ref": chunk.source_ref,
        "last_modified_iso": _iso(chunk.last_modified),
        "mime_type": chunk.mime_type,
        "extra_json": json.dumps(chunk.extra_metadata, ensure_ascii=False),
    }


def _restore(chunk_id: str, text: str, meta: dict[str, Any]) -> Chunk:
    extra_raw = meta.get("extra_json", "")
    extra = json.loads(extra_raw) if extra_raw else {}
    return Chunk(
        id=chunk_id,
        doc_id=str(meta.get("doc_id", "")),
        chunk_index=int(meta.get("chunk_index", 0)),
        text=text,
        title=str(meta.get("title", "")),
        source_type=str(meta.get("source_type", "")),
        source_ref=str(meta.get("source_ref", "")),
        last_modified=_parse_iso(str(meta.get("last_modified_iso", ""))),
        mime_type=str(meta.get("mime_type", "")),
        extra_metadata=extra,
    )


class VectorStore:
    def __init__(self, persist_path: Path, collection_name: str):
        import chromadb

        persist_path = Path(persist_path)
        persist_path.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(persist_path))
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert_chunks(self, chunks: list[Chunk], embeddings: np.ndarray) -> None:
        if not chunks:
            return
        if len(chunks) != len(embeddings):
            raise ValueError(
                f"chunks ({len(chunks)}) and embeddings ({len(embeddings)}) length mismatch"
            )
        self._collection.upsert(
            ids=[c.id for c in chunks],
            embeddings=[e.tolist() for e in embeddings],
            metadatas=[_flatten(c) for c in chunks],
            documents=[c.text for c in chunks],
        )

    def delete_document(self, doc_id: str) -> None:
        self._collection.delete(where={"doc_id": doc_id})

    def query(self, query_emb: np.ndarray, top_k: int) -> list[RetrievedChunk]:
        if top_k <= 0 or self.count() == 0:
            return []
        # Chroma expects a 2D list of query embeddings.
        arr = query_emb if query_emb.ndim == 2 else query_emb.reshape(1, -1)
        result = self._collection.query(
            query_embeddings=arr.tolist(),
            n_results=min(top_k, self.count()),
        )
        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]

        out: list[RetrievedChunk] = []
        for cid, text, meta, dist in zip(ids, docs, metas, distances):
            chunk = _restore(cid, text or "", meta or {})
            similarity = 1.0 - float(dist) / 2.0
            out.append(RetrievedChunk(chunk=chunk, similarity_score=similarity))
        # Chroma already returns sorted by distance ascending, which is
        # similarity descending after conversion. Re-sort defensively.
        out.sort(key=lambda r: r.similarity_score, reverse=True)
        return out

    def count(self) -> int:
        return self._collection.count()

    def all_doc_ids(self) -> set[str]:
        if self.count() == 0:
            return set()
        result = self._collection.get(include=["metadatas"])
        metas = result.get("metadatas") or []
        return {str(m.get("doc_id")) for m in metas if m and m.get("doc_id")}
