"""Indexer tests — fake embed function avoids loading bge-m3 in CI."""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Iterator

import numpy as np
import pytest

from src.rag.connectors.base import SourceConnector
from src.rag.indexer import (
    MANIFEST_VERSION,
    IndexReport,
    load_manifest,
    manifest_path_for,
    run_indexer,
    save_manifest,
    verify,
)
from src.rag.store import VectorStore
from src.rag.types import Document


def _fake_embed(texts: list[str]) -> np.ndarray:
    """Deterministic text-hash → unit vector. Dimension = 16."""
    if not texts:
        return np.zeros((0, 16), dtype=np.float32)
    vecs = []
    for t in texts:
        digest = hashlib.sha256(t.encode("utf-8")).digest()[:16]
        v = np.frombuffer(digest, dtype=np.uint8).astype(np.float32)
        norm = float(np.linalg.norm(v))
        vecs.append(v / (norm if norm > 0 else 1.0))
    return np.stack(vecs)


class _MemoryConnector(SourceConnector):
    """Yields pre-built documents without touching any external system."""

    def __init__(self, source_type: str, docs: list[Document]):
        self.source_type = source_type
        self._docs = docs

    def iter_documents(self) -> Iterator[Document]:
        yield from self._docs


def _doc(
    doc_id: str,
    content: str,
    *,
    source_type: str = "local",
    source_ref: str = "x.md",
) -> Document:
    return Document(
        id=doc_id,
        source_type=source_type,
        source_ref=source_ref,
        title="Title",
        content=content,
        last_modified=None,
        mime_type="text/markdown",
    )


@pytest.fixture
def store_and_manifest(tmp_path):
    store = VectorStore(tmp_path / "vs", "test_indexer")
    mpath = tmp_path / "vs" / "manifest.json"
    return store, mpath


def _run(
    connectors,
    store,
    mpath,
    *,
    force=False,
    dry_run=False,
    min_doc_chars=5,
    embed_fn=_fake_embed,
) -> IndexReport:
    return run_indexer(
        connectors,
        store=store,
        manifest_path=mpath,
        chunk_size=100,
        chunk_overlap=10,
        min_document_chars=min_doc_chars,
        embed_fn=embed_fn,
        force=force,
        dry_run=dry_run,
    )


# ---- manifest I/O ------------------------------------------------------


def test_missing_manifest_returns_fresh(tmp_path):
    m = load_manifest(tmp_path / "nope.json")
    assert m["version"] == MANIFEST_VERSION
    assert m["documents"] == {}


def test_manifest_version_mismatch_resets(tmp_path):
    mpath = tmp_path / "manifest.json"
    mpath.write_text(
        json.dumps({"version": 999, "documents": {"x": {"content_hash": "foo"}}}),
        encoding="utf-8",
    )
    m = load_manifest(mpath)
    assert m["version"] == MANIFEST_VERSION
    assert m["documents"] == {}


def test_manifest_malformed_json_resets(tmp_path):
    mpath = tmp_path / "manifest.json"
    mpath.write_text("{not json", encoding="utf-8")
    m = load_manifest(mpath)
    assert m["documents"] == {}


def test_save_manifest_roundtrip(tmp_path):
    mpath = tmp_path / "manifest.json"
    manifest = {
        "version": MANIFEST_VERSION,
        "documents": {"local:a.md": {"content_hash": "abc", "source_type": "local"}},
    }
    save_manifest(mpath, manifest)
    loaded = load_manifest(mpath)
    assert loaded["documents"] == manifest["documents"]
    assert loaded["updated_at"] is not None


def test_manifest_path_for_nested_under_vectorstore(tmp_path):
    assert manifest_path_for(tmp_path).name == "manifest.json"
    assert manifest_path_for(tmp_path).parent == tmp_path


def test_manifest_path_for_accepts_str():
    assert manifest_path_for("data/vectorstore").name == "manifest.json"


# ---- core orchestration ------------------------------------------------


def test_initial_index_adds_documents(store_and_manifest):
    store, mpath = store_and_manifest
    docs = [
        _doc("local:a.md", "alpha alpha alpha"),
        _doc("local:b.md", "beta beta beta"),
    ]
    report = _run([_MemoryConnector("local", docs)], store, mpath)
    assert report.added == 2
    assert report.updated == 0
    assert report.skipped == 0
    assert report.deleted == 0
    assert report.errors == 0
    assert report.chunks_total >= 2
    manifest = load_manifest(mpath)
    assert set(manifest["documents"]) == {"local:a.md", "local:b.md"}
    assert manifest["documents"]["local:a.md"]["source_type"] == "local"
    assert len(manifest["documents"]["local:a.md"]["content_hash"]) == 64
    assert store.all_doc_ids() == {"local:a.md", "local:b.md"}


def test_rerun_skips_unchanged(store_and_manifest):
    store, mpath = store_and_manifest
    docs = [_doc("local:a.md", "alpha"), _doc("local:b.md", "beta")]
    _run([_MemoryConnector("local", docs)], store, mpath)

    report = _run([_MemoryConnector("local", docs)], store, mpath)
    assert report.skipped == 2
    assert report.added == 0
    assert report.updated == 0
    assert report.deleted == 0


def test_content_change_updates(store_and_manifest):
    store, mpath = store_and_manifest
    _run([_MemoryConnector("local", [_doc("local:a.md", "original")])], store, mpath)
    report = _run(
        [_MemoryConnector("local", [_doc("local:a.md", "CHANGED")])],
        store,
        mpath,
    )
    assert report.updated == 1
    assert report.added == 0
    assert report.skipped == 0


def test_deletion_detected_for_active_source(store_and_manifest):
    store, mpath = store_and_manifest
    _run(
        [_MemoryConnector("local", [
            _doc("local:a.md", "alpha"), _doc("local:b.md", "beta"),
        ])],
        store,
        mpath,
    )
    report = _run(
        [_MemoryConnector("local", [_doc("local:a.md", "alpha")])],
        store,
        mpath,
    )
    assert report.deleted == 1
    assert report.skipped == 1
    manifest = load_manifest(mpath)
    assert "local:b.md" not in manifest["documents"]
    assert store.all_doc_ids() == {"local:a.md"}


def test_per_source_delete_isolation(store_and_manifest):
    store, mpath = store_and_manifest
    local_docs = [_doc("local:a.md", "alpha"), _doc("local:b.md", "beta")]
    _run([_MemoryConnector("local", local_docs)], store, mpath)

    notion_docs = [
        _doc("notion:page:1", "gamma", source_type="notion", source_ref="1"),
    ]
    report = _run([_MemoryConnector("notion", notion_docs)], store, mpath)
    assert report.added == 1
    assert report.deleted == 0
    assert report.skipped == 0
    manifest = load_manifest(mpath)
    assert set(manifest["documents"]) == {
        "local:a.md",
        "local:b.md",
        "notion:page:1",
    }
    assert store.all_doc_ids() == {"local:a.md", "local:b.md", "notion:page:1"}


def test_embed_failure_leaves_state_unchanged(store_and_manifest):
    store, mpath = store_and_manifest
    _run(
        [_MemoryConnector("local", [_doc("local:a.md", "alpha")])],
        store,
        mpath,
    )
    state_before = store.all_doc_ids()
    manifest_before = {
        k: dict(v) for k, v in load_manifest(mpath)["documents"].items()
    }

    def failing_embed(texts):
        raise RuntimeError("boom")

    docs = [_doc("local:a.md", "alpha"), _doc("local:c.md", "new content")]
    report = _run(
        [_MemoryConnector("local", docs)],
        store,
        mpath,
        embed_fn=failing_embed,
    )
    assert report.errors == 1
    assert report.skipped == 1  # a unchanged
    assert report.added == 0
    assert store.all_doc_ids() == state_before
    manifest_after = load_manifest(mpath)["documents"]
    assert "local:c.md" not in manifest_after
    assert manifest_after["local:a.md"] == manifest_before["local:a.md"]


def test_force_reindexes_unchanged(store_and_manifest):
    store, mpath = store_and_manifest
    docs = [_doc("local:a.md", "alpha")]
    _run([_MemoryConnector("local", docs)], store, mpath)
    report = _run([_MemoryConnector("local", docs)], store, mpath, force=True)
    assert report.updated == 1
    assert report.skipped == 0


def test_dry_run_does_not_mutate(store_and_manifest):
    store, mpath = store_and_manifest
    report = _run(
        [_MemoryConnector("local", [_doc("local:a.md", "alpha")])],
        store,
        mpath,
        dry_run=True,
    )
    assert report.added == 1
    assert report.chunks_total >= 1
    assert store.count() == 0
    assert not mpath.exists()


def test_dry_run_counts_deletion_without_mutating(store_and_manifest):
    store, mpath = store_and_manifest
    _run(
        [_MemoryConnector("local", [
            _doc("local:a.md", "alpha"), _doc("local:b.md", "beta"),
        ])],
        store,
        mpath,
    )
    manifest_before = load_manifest(mpath)
    store_ids_before = store.all_doc_ids()

    report = _run(
        [_MemoryConnector("local", [_doc("local:a.md", "alpha")])],
        store,
        mpath,
        dry_run=True,
    )
    assert report.deleted == 1
    assert report.skipped == 1
    # State unchanged
    assert load_manifest(mpath) == manifest_before
    assert store.all_doc_ids() == store_ids_before


def test_empty_content_skipped(store_and_manifest):
    store, mpath = store_and_manifest
    report = _run(
        [_MemoryConnector("local", [_doc("local:e.md", "   \n\n")])],
        store,
        mpath,
    )
    assert report.added == 0
    assert report.errors == 0
    manifest = load_manifest(mpath)
    assert "local:e.md" not in manifest["documents"]


def test_short_document_still_indexed(store_and_manifest, caplog):
    store, mpath = store_and_manifest
    caplog.set_level(logging.WARNING, logger="src.rag.indexer")
    report = _run(
        [_MemoryConnector("local", [_doc("local:s.md", "tiny")])],
        store,
        mpath,
        min_doc_chars=20,
    )
    assert report.added == 1
    assert any("short_document" in rec.message for rec in caplog.records)


def test_verify_reports_drift(store_and_manifest):
    store, mpath = store_and_manifest
    _run(
        [_MemoryConnector("local", [
            _doc("local:a.md", "alpha"), _doc("local:b.md", "beta"),
        ])],
        store,
        mpath,
    )
    store.delete_document("local:a.md")
    result = verify(store, mpath)
    assert result["manifest_only"] == ["local:a.md"]
    assert result["store_only"] == []
    assert result["matched"] == 1


def test_stored_chunks_are_queryable_after_index(store_and_manifest):
    store, mpath = store_and_manifest
    _run(
        [_MemoryConnector("local", [
            _doc("local:a.md", "alpha alpha alpha content"),
            _doc("local:b.md", "beta beta beta content"),
        ])],
        store,
        mpath,
    )
    query_emb = _fake_embed(["alpha alpha alpha content"])
    results = store.query(query_emb, top_k=2)
    assert len(results) >= 1
    assert results[0].chunk.doc_id == "local:a.md"
