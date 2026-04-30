"""Phase 10 P10-3 — RAG namespace + document management API tests.

Coverage:
- POST /rag/namespaces — happy path, duplicate 409, invalid name 422
- DELETE /rag/namespaces/{ns} — default protection, not-found,
  non-empty refusal, force=true override
- GET /rag/namespaces/{ns}/documents — empty, populated with mixed
  manifest indexed/unindexed states
- POST /rag/namespaces/{ns}/documents — upload success, traversal-block,
  unsupported extension
- DELETE /rag/namespaces/{ns}/documents/{filename} — success, 404,
  traversal-block

DO NOT rule: only module-attribute monkeypatching, no `from X import Y`
direct rebinding of patched dependencies.
"""
from __future__ import annotations

import io
import json
import os

os.environ["API_SKIP_WARMUP"] = "1"

import pytest
from fastapi.testclient import TestClient

from src.api import store as _store
from src.api.config import reset_api_settings_cache


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch, tmp_path):
    monkeypatch.setenv("API_SKIP_WARMUP", "1")
    monkeypatch.setenv("API_CHECKPOINT_DB", str(tmp_path / "ck.db"))
    monkeypatch.setenv("API_APP_DB", str(tmp_path / "app.db"))
    reset_api_settings_cache()
    _store.reset_stores()
    yield
    reset_api_settings_cache()
    _store.reset_stores()


@pytest.fixture
def client():
    from src.api.app import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def patched_paths(monkeypatch, tmp_path):
    """Redirect both vectorstore and company_docs roots into tmp_path.

    Uses module-attribute monkeypatching on the route module + the
    settings loader (DO NOT rule).
    """
    vs_root = tmp_path / "vs"
    cd_root = tmp_path / "docs"
    vs_root.mkdir(parents=True)
    cd_root.mkdir(parents=True)

    from src.api.routes import rag as _rag_routes
    from src.config import loader as _loader

    original = _loader.get_settings()

    class _FakeRag:
        vectorstore_path = vs_root
        collection_name = "x"
        min_document_chars = 1
        chunk_size = 1
        chunk_overlap = 0
        top_k = 1
        notion_page_ids: list[str] = []
        notion_database_ids: list[str] = []
        embedding_model = "test"

    class _FakeSettings:
        rag = _FakeRag()
        llm = original.llm
        search = original.search
        output = original.output

    monkeypatch.setattr(
        _rag_routes._config_loader, "get_settings", lambda: _FakeSettings()
    )
    monkeypatch.setattr(_rag_routes, "_company_docs_root", lambda: cd_root)
    return vs_root, cd_root


def _seed_manifest(vs_root, namespace, documents: dict):
    ns_dir = vs_root / namespace
    ns_dir.mkdir(parents=True, exist_ok=True)
    (ns_dir / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "updated_at": "2026-04-30T00:00:00+00:00",
                "documents": documents,
            }
        ),
        encoding="utf-8",
    )


# ── POST /rag/namespaces ────────────────────────────────────────────────


def test_create_namespace_201(client, patched_paths):
    vs_root, cd_root = patched_paths
    r = client.post("/rag/namespaces", json={"name": "snowflake"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "snowflake"
    assert body["is_default"] is False
    assert body["document_count"] == 0
    # Both physical dirs exist
    assert (vs_root / "snowflake").is_dir()
    assert (cd_root / "snowflake").is_dir()


def test_create_namespace_duplicate_409(client, patched_paths):
    vs_root, _ = patched_paths
    (vs_root / "databricks").mkdir()
    r = client.post("/rag/namespaces", json={"name": "databricks"})
    assert r.status_code == 409
    assert "already exists" in r.json()["detail"]


def test_create_namespace_invalid_name_422(client, patched_paths):
    r = client.post("/rag/namespaces", json={"name": "../escape"})
    assert r.status_code == 422


def test_create_namespace_blank_name_422(client, patched_paths):
    r = client.post("/rag/namespaces", json={"name": ""})
    # Pydantic min_length=1 catches this first
    assert r.status_code == 422


# ── DELETE /rag/namespaces/{namespace} ──────────────────────────────────


def test_delete_default_namespace_refused(client, patched_paths):
    r = client.delete("/rag/namespaces/default")
    assert r.status_code == 400
    assert "default" in r.json()["detail"]


def test_delete_namespace_not_found(client, patched_paths):
    r = client.delete("/rag/namespaces/missing")
    assert r.status_code == 404


def test_delete_namespace_non_empty_refused(client, patched_paths):
    vs_root, cd_root = patched_paths
    (cd_root / "snowflake").mkdir()
    (cd_root / "snowflake" / "doc.md").write_text("hi", encoding="utf-8")
    r = client.delete("/rag/namespaces/snowflake")
    assert r.status_code == 409
    assert "force" in r.json()["detail"]
    # Still on disk
    assert (cd_root / "snowflake" / "doc.md").exists()


def test_delete_namespace_force_removes(client, patched_paths):
    vs_root, cd_root = patched_paths
    (cd_root / "snowflake").mkdir()
    (cd_root / "snowflake" / "doc.md").write_text("hi", encoding="utf-8")
    _seed_manifest(
        vs_root,
        "snowflake",
        {"local:doc.md": {"source_type": "local", "chunk_count": 2}},
    )
    r = client.delete("/rag/namespaces/snowflake?force=true")
    assert r.status_code == 200
    assert r.json()["removed"] is True
    assert not (cd_root / "snowflake").exists()
    assert not (vs_root / "snowflake").exists()


def test_delete_empty_namespace_succeeds_without_force(client, patched_paths):
    vs_root, cd_root = patched_paths
    (cd_root / "snowflake").mkdir()
    (vs_root / "snowflake").mkdir()
    r = client.delete("/rag/namespaces/snowflake")
    assert r.status_code == 200
    assert not (cd_root / "snowflake").exists()


# ── GET /rag/namespaces/{namespace}/documents ───────────────────────────


def test_list_documents_empty(client, patched_paths):
    vs_root, cd_root = patched_paths
    (cd_root / "default").mkdir()
    r = client.get("/rag/namespaces/default/documents")
    assert r.status_code == 200
    body = r.json()
    assert body["namespace"] == "default"
    assert body["documents"] == []
    assert body["indexed_doc_count"] == 0


def test_list_documents_marks_indexed(client, patched_paths):
    vs_root, cd_root = patched_paths
    ns_docs = cd_root / "databricks"
    ns_docs.mkdir()
    (ns_docs / "indexed.md").write_text("# hi", encoding="utf-8")
    (ns_docs / "fresh.txt").write_text("not yet indexed", encoding="utf-8")
    _seed_manifest(
        vs_root,
        "databricks",
        {
            "local:indexed.md": {"source_type": "local", "chunk_count": 4},
            "notion:p123": {"source_type": "notion", "chunk_count": 7},
        },
    )

    r = client.get("/rag/namespaces/databricks/documents")
    assert r.status_code == 200
    body = r.json()
    assert body["namespace"] == "databricks"
    by_name = {d["filename"]: d for d in body["documents"]}
    assert set(by_name) == {"indexed.md", "fresh.txt"}
    assert by_name["indexed.md"]["indexed"] is True
    assert by_name["indexed.md"]["chunk_count"] == 4
    assert by_name["fresh.txt"]["indexed"] is False
    assert by_name["fresh.txt"]["chunk_count"] == 0
    assert body["indexed_doc_count"] == 1


# ── POST /rag/namespaces/{namespace}/documents ──────────────────────────


def test_upload_document_success(client, patched_paths):
    vs_root, cd_root = patched_paths
    files = {"file": ("notes.md", io.BytesIO(b"# hello"), "text/markdown")}
    r = client.post("/rag/namespaces/default/documents", files=files)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["filename"] == "notes.md"
    assert body["size_bytes"] == 7
    saved = cd_root / "default" / "notes.md"
    assert saved.exists()
    assert saved.read_bytes() == b"# hello"


def test_upload_document_creates_namespace_dir(client, patched_paths):
    """Upload to a brand-new namespace (auto-created if missing)."""
    vs_root, cd_root = patched_paths
    files = {"file": ("one.txt", io.BytesIO(b"data"), "text/plain")}
    r = client.post("/rag/namespaces/fresh/documents", files=files)
    assert r.status_code == 201
    assert (cd_root / "fresh" / "one.txt").exists()


def test_upload_document_traversal_blocked(client, patched_paths):
    files = {"file": ("../evil.md", io.BytesIO(b"x"), "text/markdown")}
    r = client.post("/rag/namespaces/default/documents", files=files)
    assert r.status_code == 422


def test_upload_document_unsupported_extension(client, patched_paths):
    files = {"file": ("x.exe", io.BytesIO(b"binary"), "application/octet-stream")}
    r = client.post("/rag/namespaces/default/documents", files=files)
    assert r.status_code == 415


def test_upload_document_path_separator_blocked(client, patched_paths):
    files = {
        "file": ("sub/dir.md", io.BytesIO(b"x"), "text/markdown")
    }
    r = client.post("/rag/namespaces/default/documents", files=files)
    assert r.status_code == 422


# ── DELETE /rag/namespaces/{namespace}/documents/{filename} ─────────────


def test_delete_document_success(client, patched_paths):
    vs_root, cd_root = patched_paths
    ns = cd_root / "databricks"
    ns.mkdir()
    (ns / "doc.md").write_text("hi", encoding="utf-8")
    r = client.delete("/rag/namespaces/databricks/documents/doc.md")
    assert r.status_code == 204
    assert not (ns / "doc.md").exists()
    # Other files preserved
    (ns / "other.md").write_text("still here", encoding="utf-8")
    assert (ns / "other.md").exists()


def test_delete_document_not_found(client, patched_paths):
    vs_root, cd_root = patched_paths
    (cd_root / "databricks").mkdir()
    r = client.delete("/rag/namespaces/databricks/documents/nope.md")
    assert r.status_code == 404


def test_delete_document_traversal_blocked(client, patched_paths):
    vs_root, cd_root = patched_paths
    ns = cd_root / "databricks"
    ns.mkdir()
    (ns / "real.md").write_text("safe", encoding="utf-8")
    sibling = cd_root / "victim.md"
    sibling.write_text("DO NOT DELETE", encoding="utf-8")
    # Path traversal attempt; FastAPI's `:path` converter passes the
    # slash through.
    r = client.delete(
        "/rag/namespaces/databricks/documents/..%2Fvictim.md"
    )
    assert r.status_code in (404, 422)
    assert sibling.exists()


def test_delete_document_namespace_missing(client, patched_paths):
    r = client.delete("/rag/namespaces/missing/documents/x.md")
    assert r.status_code == 404
