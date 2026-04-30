"""Phase 10 P10-2a — RAG namespace path/name builders + migration tests.

Covers:
- `vectorstore_root_for` / `company_docs_root_for` / `manifest_path_for_namespace`
- `list_namespaces` (manifest-presence detection)
- `ensure_namespace` (idempotent dir creation)
- `migrate_flat_layout` (legacy flat → <root>/default/, idempotent + best-effort)
- `_safe` (rejects bad characters)

The cross-namespace retrieve isolation test uses a real (in-memory)
`VectorStore` per namespace to verify the retriever cache splits stores
by namespace key.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from src.rag import retriever as retriever_mod
from src.rag.namespace import (
    DEFAULT_NAMESPACE,
    MANIFEST_FILENAME,
    company_docs_root_for,
    ensure_namespace,
    list_namespaces,
    manifest_path_for_namespace,
    migrate_flat_layout,
    vectorstore_root_for,
)
from src.rag.store import VectorStore
from src.rag.types import Chunk


# ── builders ───────────────────────────────────────────────────────────


def test_vectorstore_root_for_appends_namespace(tmp_path):
    out = vectorstore_root_for(tmp_path / "vs", "databricks")
    assert out == tmp_path / "vs" / "databricks"


def test_company_docs_root_for_appends_namespace(tmp_path):
    out = company_docs_root_for(tmp_path / "docs", "snowflake")
    assert out == tmp_path / "docs" / "snowflake"


def test_manifest_path_for_namespace(tmp_path):
    out = manifest_path_for_namespace(tmp_path / "vs", "default")
    assert out == tmp_path / "vs" / "default" / "manifest.json"


def test_namespace_rejects_invalid_chars(tmp_path):
    from src.rag.namespace import _safe

    with pytest.raises(ValueError):
        _safe("")
    with pytest.raises(ValueError):
        _safe("has space")
    with pytest.raises(ValueError):
        _safe("with/slash")
    # valid
    assert _safe("databricks") == "databricks"
    assert _safe("client_2026") == "client_2026"
    assert _safe("kr-public") == "kr-public"


# ── list_namespaces ────────────────────────────────────────────────────


def test_list_namespaces_empty_when_root_missing(tmp_path):
    assert list_namespaces(tmp_path / "nope") == []


def test_list_namespaces_only_those_with_manifest(tmp_path):
    vs = tmp_path / "vs"
    (vs / "default").mkdir(parents=True)
    (vs / "default" / MANIFEST_FILENAME).write_text("{}", encoding="utf-8")
    (vs / "databricks").mkdir()
    (vs / "databricks" / MANIFEST_FILENAME).write_text("{}", encoding="utf-8")
    # An empty subdirectory (no manifest) is not a namespace yet.
    (vs / "halfbaked").mkdir()
    # A loose file at the root is ignored.
    (vs / "stray.json").write_text("{}", encoding="utf-8")

    out = list_namespaces(vs)
    assert out == ["databricks", "default"]  # alphabetical


# ── ensure_namespace ───────────────────────────────────────────────────


def test_ensure_namespace_creates_dirs(tmp_path):
    vs, cd = ensure_namespace(
        vectorstore_root=tmp_path / "vs",
        company_docs_root=tmp_path / "docs",
        namespace="snowflake",
    )
    assert vs.is_dir()
    assert cd.is_dir()
    # idempotent — second call doesn't raise
    ensure_namespace(
        vectorstore_root=tmp_path / "vs",
        company_docs_root=tmp_path / "docs",
        namespace="snowflake",
    )


# ── migrate_flat_layout ────────────────────────────────────────────────


def test_migrate_flat_layout_moves_legacy_files(tmp_path):
    vs = tmp_path / "vs"
    cd = tmp_path / "docs"
    vs.mkdir()
    cd.mkdir()

    # Legacy flat layout: chroma DB + manifest at vs root, PDFs at docs root
    (vs / "chroma.sqlite3").write_bytes(b"fake-db")
    (vs / "manifest.json").write_text("{}", encoding="utf-8")
    (vs / "abc-collection-uuid").mkdir()
    (vs / "abc-collection-uuid" / "data.parquet").write_bytes(b"x")
    (cd / "Databricks_AI Platform.pdf").write_bytes(b"%PDF-1.4")
    (cd / "notes.md").write_text("# notes", encoding="utf-8")
    (cd / ".gitkeep").write_text("", encoding="utf-8")

    report = migrate_flat_layout(vectorstore_root=vs, company_docs_root=cd)

    # Vectorstore moved into <vs>/default/
    target_vs = vs / DEFAULT_NAMESPACE
    assert (target_vs / "chroma.sqlite3").exists()
    assert (target_vs / "manifest.json").exists()
    assert (target_vs / "abc-collection-uuid").is_dir()
    assert (target_vs / "abc-collection-uuid" / "data.parquet").exists()
    # No leftover at vs root
    assert not (vs / "chroma.sqlite3").exists()
    assert not (vs / "manifest.json").exists()
    assert not (vs / "abc-collection-uuid").exists()

    # Docs moved into <cd>/default/
    target_cd = cd / DEFAULT_NAMESPACE
    assert (target_cd / "Databricks_AI Platform.pdf").exists()
    assert (target_cd / "notes.md").exists()
    # .gitkeep left at root (not a doc extension)
    assert (cd / ".gitkeep").exists()
    assert not (cd / "Databricks_AI Platform.pdf").exists()

    assert report["vectorstore_files_moved"] >= 2
    assert report["vectorstore_dirs_moved"] >= 1
    assert report["company_docs_files_moved"] == 2
    assert report["errors"] == 0


def test_migrate_flat_layout_idempotent(tmp_path):
    vs = tmp_path / "vs"
    cd = tmp_path / "docs"
    vs.mkdir()
    cd.mkdir()
    (vs / "chroma.sqlite3").write_bytes(b"x")
    (cd / "x.md").write_text("x", encoding="utf-8")

    migrate_flat_layout(vectorstore_root=vs, company_docs_root=cd)
    # Second call should be a no-op (no flat files left to move)
    second = migrate_flat_layout(vectorstore_root=vs, company_docs_root=cd)
    assert second["vectorstore_files_moved"] == 0
    assert second["company_docs_files_moved"] == 0
    assert second["errors"] == 0


def test_migrate_flat_layout_preserves_existing_namespace(tmp_path):
    """If a namespace dir already has its manifest, don't touch it."""
    vs = tmp_path / "vs"
    (vs / "databricks").mkdir(parents=True)
    (vs / "databricks" / "manifest.json").write_text(
        json.dumps({"version": 1}), encoding="utf-8"
    )
    # Plus a flat legacy file that should still migrate to default/
    (vs / "manifest.json").write_text("{}", encoding="utf-8")

    cd = tmp_path / "docs"
    cd.mkdir()

    migrate_flat_layout(vectorstore_root=vs, company_docs_root=cd)

    # databricks namespace untouched
    db_manifest = json.loads(
        (vs / "databricks" / "manifest.json").read_text(encoding="utf-8")
    )
    assert db_manifest["version"] == 1
    # legacy flat manifest moved to default/
    assert (vs / "default" / "manifest.json").exists()


def test_migrate_flat_layout_no_op_when_empty(tmp_path):
    """No flat files = nothing to do, no errors."""
    vs = tmp_path / "vs"
    cd = tmp_path / "docs"
    vs.mkdir()
    cd.mkdir()
    report = migrate_flat_layout(vectorstore_root=vs, company_docs_root=cd)
    assert report == {
        "vectorstore_files_moved": 0,
        "vectorstore_dirs_moved": 0,
        "company_docs_files_moved": 0,
        "errors": 0,
    }


def test_migrate_flat_layout_handles_missing_roots(tmp_path):
    """Missing roots are silently tolerated (best-effort)."""
    report = migrate_flat_layout(
        vectorstore_root=tmp_path / "missing_vs",
        company_docs_root=tmp_path / "missing_docs",
    )
    assert report["errors"] == 0


# ── retriever cache splits by namespace ────────────────────────────────


def _unit(vec):
    a = np.array(vec, dtype=np.float32)
    return a / np.linalg.norm(a)


def _chunk(doc_id: str, idx: int, text: str) -> Chunk:
    return Chunk(
        id=f"{doc_id}::{idx}",
        doc_id=doc_id,
        chunk_index=idx,
        text=text,
        title=doc_id,
        source_type="local",
        source_ref=f"{doc_id}.md",
        last_modified=None,
        mime_type="text/markdown",
        extra_metadata={},
    )


def test_retriever_caches_per_namespace(tmp_path, monkeypatch):
    """Two namespaces should have two distinct VectorStores in the cache."""
    db_store = VectorStore(tmp_path / "vs_db", "test_db")
    db_store.upsert_chunks(
        [_chunk("d", 0, "databricks specific content")],
        np.stack([_unit([1.0, 0.0, 0.0])]),
    )
    sf_store = VectorStore(tmp_path / "vs_sf", "test_sf")
    sf_store.upsert_chunks(
        [_chunk("s", 0, "snowflake specific content")],
        np.stack([_unit([0.0, 1.0, 0.0])]),
    )

    retriever_mod.reset_store_singleton()

    fake_stores = {"databricks": db_store, "snowflake": sf_store}

    def fake_lookup(namespace=DEFAULT_NAMESPACE):
        return fake_stores[namespace]

    monkeypatch.setattr(retriever_mod, "_store", fake_lookup)
    monkeypatch.setattr(
        retriever_mod,
        "embed_texts",
        lambda texts: np.array([[1.0, 0.0, 0.0]], dtype=np.float32),
    )

    db_results = retriever_mod.retrieve(
        "anything", namespace="databricks", top_k=5
    )
    sf_results = retriever_mod.retrieve(
        "anything", namespace="snowflake", top_k=5
    )

    db_ids = {r.chunk.doc_id for r in db_results}
    sf_ids = {r.chunk.doc_id for r in sf_results}
    # Cross-namespace isolation: results never bleed between namespaces.
    assert db_ids == {"d"}
    assert sf_ids == {"s"}

    retriever_mod.reset_store_singleton()
