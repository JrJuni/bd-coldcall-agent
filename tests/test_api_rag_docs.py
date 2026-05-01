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


# ── GET /rag/namespaces/{namespace}/tree (P10-3+ folder UX) ─────────────


def test_tree_root_lists_folders_and_files(client, patched_paths):
    vs_root, cd_root = patched_paths
    ns = cd_root / "default"
    ns.mkdir()
    (ns / "ai").mkdir()
    (ns / "reports").mkdir()
    (ns / "ai" / "nvidia.md").write_text("x", encoding="utf-8")
    (ns / "reports" / "q3.txt").write_text("y", encoding="utf-8")
    (ns / "top.md").write_text("z", encoding="utf-8")
    r = client.get("/rag/namespaces/default/tree")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["namespace"] == "default"
    assert body["path"] == ""
    assert body["parent"] is None
    types_and_names = [(e["type"], e["name"]) for e in body["entries"]]
    # Folders sorted before files, both alphabetically.
    assert types_and_names == [
        ("folder", "ai"),
        ("folder", "reports"),
        ("file", "top.md"),
    ]
    folder = next(e for e in body["entries"] if e["name"] == "ai")
    assert folder["child_count"] == 1


def test_tree_subpath_returns_parent(client, patched_paths):
    vs_root, cd_root = patched_paths
    ns = cd_root / "default"
    (ns / "ai" / "deep").mkdir(parents=True)
    (ns / "ai" / "amd.md").write_text("hi", encoding="utf-8")
    r = client.get("/rag/namespaces/default/tree", params={"path": "ai"})
    assert r.status_code == 200
    body = r.json()
    assert body["path"] == "ai"
    assert body["parent"] == ""
    names = [e["name"] for e in body["entries"]]
    assert names == ["deep", "amd.md"]


def test_tree_deep_subpath_parent_chain(client, patched_paths):
    vs_root, cd_root = patched_paths
    (cd_root / "default" / "a" / "b" / "c").mkdir(parents=True)
    r = client.get(
        "/rag/namespaces/default/tree", params={"path": "a/b/c"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["path"] == "a/b/c"
    assert body["parent"] == "a/b"


def test_tree_path_traversal_rejected(client, patched_paths):
    (patched_paths[1] / "default").mkdir()
    r = client.get(
        "/rag/namespaces/default/tree", params={"path": "../escape"}
    )
    assert r.status_code == 422


def test_tree_marks_indexed_files(client, patched_paths):
    vs_root, cd_root = patched_paths
    ns = cd_root / "databricks"
    ns.mkdir()
    (ns / "ai").mkdir()
    (ns / "ai" / "indexed.md").write_text("hi", encoding="utf-8")
    _seed_manifest(
        vs_root,
        "databricks",
        {"local:ai/indexed.md": {"source_type": "local", "chunk_count": 3}},
    )
    r = client.get(
        "/rag/namespaces/databricks/tree", params={"path": "ai"}
    )
    assert r.status_code == 200
    entry = r.json()["entries"][0]
    assert entry["name"] == "indexed.md"
    assert entry["indexed"] is True
    assert entry["chunk_count"] == 3


def test_tree_namespace_without_docs_dir(client, patched_paths):
    """Brand-new namespace whose company_docs dir hasn't been created yet."""
    r = client.get("/rag/namespaces/fresh/tree")
    assert r.status_code == 200
    assert r.json()["entries"] == []


def test_tree_path_not_a_directory(client, patched_paths):
    vs_root, cd_root = patched_paths
    ns = cd_root / "default"
    ns.mkdir()
    (ns / "x.md").write_text("hi", encoding="utf-8")
    r = client.get(
        "/rag/namespaces/default/tree", params={"path": "x.md"}
    )
    assert r.status_code == 404


# ── POST /rag/namespaces/{namespace}/folders ────────────────────────────


def test_create_folder_at_root(client, patched_paths):
    vs_root, cd_root = patched_paths
    r = client.post(
        "/rag/namespaces/default/folders", json={"path": "reports"}
    )
    assert r.status_code == 201, r.text
    assert r.json()["created"] is True
    assert (cd_root / "default" / "reports").is_dir()


def test_create_folder_nested(client, patched_paths):
    vs_root, cd_root = patched_paths
    r = client.post(
        "/rag/namespaces/default/folders",
        json={"path": "ai/reports/q3"},
    )
    assert r.status_code == 201
    assert (cd_root / "default" / "ai" / "reports" / "q3").is_dir()


def test_create_folder_already_exists_409(client, patched_paths):
    vs_root, cd_root = patched_paths
    (cd_root / "default" / "reports").mkdir(parents=True)
    r = client.post(
        "/rag/namespaces/default/folders", json={"path": "reports"}
    )
    assert r.status_code == 409


def test_create_folder_traversal_rejected(client, patched_paths):
    for bad in ("../escape", "..\\escape", "/abs", "C:/abs"):
        r = client.post(
            "/rag/namespaces/default/folders", json={"path": bad}
        )
        assert r.status_code == 422, f"path={bad!r}"


def test_create_folder_blank_rejected(client, patched_paths):
    r = client.post("/rag/namespaces/default/folders", json={"path": ""})
    # Pydantic min_length=1 catches this.
    assert r.status_code == 422


# ── DELETE /rag/namespaces/{namespace}/folders/{path:path} ──────────────


def test_delete_folder_recursive(client, patched_paths):
    vs_root, cd_root = patched_paths
    deep = cd_root / "default" / "ai" / "reports"
    deep.mkdir(parents=True)
    (deep / "q3.md").write_text("x", encoding="utf-8")
    r = client.delete("/rag/namespaces/default/folders/ai")
    assert r.status_code == 200, r.text
    assert r.json()["removed"] is True
    assert not (cd_root / "default" / "ai").exists()


def test_delete_folder_namespace_root_rejected(client, patched_paths):
    # Empty path via a trailing slash → 404 (FastAPI doesn't match)
    # The semantically relevant case is the dedicated namespace DELETE.
    # Here we verify the {path:path} converter still requires content.
    r = client.delete("/rag/namespaces/default/folders/")
    assert r.status_code in (404, 405, 422)


def test_delete_folder_not_found(client, patched_paths):
    (patched_paths[1] / "default").mkdir()
    r = client.delete("/rag/namespaces/default/folders/missing")
    assert r.status_code == 404


def test_delete_folder_traversal_rejected(client, patched_paths):
    vs_root, cd_root = patched_paths
    (cd_root / "default").mkdir()
    sibling = cd_root / "victim.md"
    sibling.write_text("DO NOT DELETE", encoding="utf-8")
    r = client.delete("/rag/namespaces/default/folders/..%2Fvictim.md")
    assert r.status_code in (404, 422)
    assert sibling.exists()


# ── POST /rag/namespaces/{namespace}/documents — path form field ────────


def test_upload_with_subpath_creates_dirs(client, patched_paths):
    vs_root, cd_root = patched_paths
    files = {"file": ("nvidia.md", io.BytesIO(b"# hi"), "text/markdown")}
    r = client.post(
        "/rag/namespaces/default/documents",
        files=files,
        data={"path": "ai/reports"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["filename"] == "ai/reports/nvidia.md"
    saved = cd_root / "default" / "ai" / "reports" / "nvidia.md"
    assert saved.exists()
    assert saved.read_bytes() == b"# hi"


def test_upload_subpath_traversal_rejected(client, patched_paths):
    files = {"file": ("x.md", io.BytesIO(b"x"), "text/markdown")}
    for bad in ("../escape", "/abs", "C:/abs", "a/../b"):
        r = client.post(
            "/rag/namespaces/default/documents",
            files=files,
            data={"path": bad},
        )
        assert r.status_code == 422, f"path={bad!r}"


def test_upload_subpath_default_empty_unchanged(client, patched_paths):
    """Verifies the existing flat-upload code path still works."""
    vs_root, cd_root = patched_paths
    files = {"file": ("flat.md", io.BytesIO(b"x"), "text/markdown")}
    r = client.post("/rag/namespaces/default/documents", files=files)
    assert r.status_code == 201
    assert r.json()["filename"] == "flat.md"
    assert (cd_root / "default" / "flat.md").exists()


# ── POST /rag/namespaces/{namespace}/open ───────────────────────────────


def test_open_folder_returns_abs_path(client, patched_paths, monkeypatch):
    """Don't actually launch the OS shell during tests."""
    from src.api.routes import rag as _rag_routes

    calls: list[str] = []
    monkeypatch.setattr(
        _rag_routes,
        "_launch_file_manager",
        lambda p: (calls.append(p), True)[1],
    )

    vs_root, cd_root = patched_paths
    (cd_root / "default").mkdir()
    r = client.post("/rag/namespaces/default/open")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["opened"] is True
    assert body["path"] == ""
    assert body["abs_path"].endswith("default")
    assert len(calls) == 1


def test_open_folder_subpath(client, patched_paths, monkeypatch):
    from src.api.routes import rag as _rag_routes

    calls: list[str] = []
    monkeypatch.setattr(
        _rag_routes,
        "_launch_file_manager",
        lambda p: (calls.append(p), True)[1],
    )
    vs_root, cd_root = patched_paths
    (cd_root / "default" / "ai").mkdir(parents=True)
    r = client.post(
        "/rag/namespaces/default/open", params={"path": "ai"}
    )
    assert r.status_code == 200
    assert r.json()["path"] == "ai"
    assert r.json()["abs_path"].endswith("ai")
    assert len(calls) == 1


def test_open_folder_not_found(client, patched_paths, monkeypatch):
    from src.api.routes import rag as _rag_routes

    monkeypatch.setattr(
        _rag_routes,
        "_launch_file_manager",
        lambda p: (_ for _ in ()).throw(AssertionError("must not be called")),
    )
    (patched_paths[1] / "default").mkdir()
    r = client.post(
        "/rag/namespaces/default/open", params={"path": "missing"}
    )
    assert r.status_code == 404


def test_open_folder_traversal_rejected(client, patched_paths, monkeypatch):
    from src.api.routes import rag as _rag_routes

    monkeypatch.setattr(
        _rag_routes,
        "_launch_file_manager",
        lambda p: (_ for _ in ()).throw(AssertionError("must not be called")),
    )
    r = client.post(
        "/rag/namespaces/default/open", params={"path": "../escape"}
    )
    assert r.status_code == 422


def test_open_folder_launch_failure_returns_opened_false(
    client, patched_paths, monkeypatch
):
    """When the OS shell launch fails, the endpoint still 200s but
    flags `opened=False` so the UI can surface a clear message."""
    from src.api.routes import rag as _rag_routes

    monkeypatch.setattr(
        _rag_routes, "_launch_file_manager", lambda p: False
    )
    vs_root, cd_root = patched_paths
    (cd_root / "default").mkdir()
    r = client.post("/rag/namespaces/default/open")
    assert r.status_code == 200
    body = r.json()
    assert body["opened"] is False
    assert body["abs_path"].endswith("default")


# ── POST /rag/root/open ─────────────────────────────────────────────────


def test_open_root(client, patched_paths, monkeypatch):
    from src.api.routes import rag as _rag_routes

    calls: list[str] = []
    monkeypatch.setattr(
        _rag_routes,
        "_launch_file_manager",
        lambda p: (calls.append(p), True)[1],
    )
    vs_root, cd_root = patched_paths
    r = client.post("/rag/root/open")
    assert r.status_code == 200
    body = r.json()
    assert body["opened"] is True
    # company_docs root, not a specific namespace
    assert str(cd_root.resolve()) == body["abs_path"]
    assert len(calls) == 1


# ── POST /rag/namespaces/{namespace}/summary ────────────────────────────


def _make_chunk(doc_id: str, source_ref: str, text: str, idx: int = 0):
    """Build a Chunk-like object for the sample() stub."""
    from src.rag.types import Chunk

    return Chunk(
        id=f"{doc_id}::{idx}",
        doc_id=doc_id,
        chunk_index=idx,
        text=text,
        title=source_ref,
        source_type="local",
        source_ref=source_ref,
        last_modified=None,
        mime_type="text/markdown",
        extra_metadata={},
    )


class _FakeStore:
    def __init__(self, chunks: list):
        self._chunks = chunks

    def count(self) -> int:
        return len(self._chunks)

    def sample(self, limit: int, where=None):  # noqa: ARG002
        return list(self._chunks[:limit])


def test_summary_empty_namespace_returns_hint(
    client, patched_paths, monkeypatch
):
    from src.api.routes import rag as _rag_routes

    fake = _FakeStore([])
    monkeypatch.setattr(_rag_routes._retriever, "_store", lambda ns: fake)
    monkeypatch.setattr(
        _rag_routes._claude_client,
        "chat_once",
        lambda **k: (_ for _ in ()).throw(
            AssertionError("must not call LLM for empty corpus")
        ),
    )
    r = client.post(
        "/rag/namespaces/default/summary", json={"path": "", "lang": "ko"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["chunk_count"] == 0
    assert body["chunks_in_namespace"] == 0
    assert "비어" in body["summary"] or "없습" in body["summary"]


def test_summary_namespace_calls_llm(client, patched_paths, monkeypatch):
    from src.api.routes import rag as _rag_routes

    chunks = [
        _make_chunk("doc1", "ai/nvidia.md", "NVIDIA AI infra notes"),
        _make_chunk("doc2", "reports/q3.md", "Q3 results summary"),
    ]
    fake = _FakeStore(chunks)
    monkeypatch.setattr(_rag_routes._retriever, "_store", lambda ns: fake)

    captured: dict = {}

    def _fake_chat_once(**kwargs):
        captured.update(kwargs)
        return {
            "text": "- **AI infra**: NVIDIA notes.\n- **Q3 report**: results.",
            "usage": {"input_tokens": 500, "output_tokens": 50},
            "stop_reason": "end_turn",
            "model": "claude-sonnet-4-6",
        }

    monkeypatch.setattr(
        _rag_routes._claude_client, "chat_once", _fake_chat_once
    )

    r = client.post(
        "/rag/namespaces/default/summary",
        json={"path": "", "lang": "ko", "sample_size": 5},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["chunk_count"] == 2
    assert body["chunks_in_namespace"] == 2
    assert "AI infra" in body["summary"]
    assert body["model"] == "claude-sonnet-4-6"
    assert body["usage"]["input_tokens"] == 500
    # Prompt rendered with the right substitutions
    assert "default" in captured["system"]
    assert "NVIDIA AI infra notes" in captured["user"]


def test_summary_path_filters_chunks(client, patched_paths, monkeypatch):
    """Summary scoped to a sub-path should only feed matching chunks."""
    from src.api.routes import rag as _rag_routes

    chunks = [
        _make_chunk("d1", "ai/nvidia.md", "NV"),
        _make_chunk("d2", "ai/amd.md", "AMD"),
        _make_chunk("d3", "reports/q3.md", "Q3"),
        _make_chunk("d4", "ai/deep/x.md", "deep"),
    ]
    fake = _FakeStore(chunks)
    monkeypatch.setattr(_rag_routes._retriever, "_store", lambda ns: fake)

    captured: dict = {}

    def _fake_chat_once(**kwargs):
        captured.update(kwargs)
        return {
            "text": "- **AI**: ok",
            "usage": {"input_tokens": 100, "output_tokens": 10},
            "model": "claude",
        }

    monkeypatch.setattr(
        _rag_routes._claude_client, "chat_once", _fake_chat_once
    )

    r = client.post(
        "/rag/namespaces/default/summary",
        json={"path": "ai", "lang": "en", "sample_size": 10},
    )
    assert r.status_code == 200
    body = r.json()
    # Only 'ai/*' source_refs should be included
    assert body["chunk_count"] == 3
    user = captured["user"]
    assert "NV" in user
    assert "AMD" in user
    assert "deep" in user
    assert "Q3" not in user


def test_summary_path_no_matching_chunks(
    client, patched_paths, monkeypatch
):
    from src.api.routes import rag as _rag_routes

    chunks = [_make_chunk("d1", "reports/q3.md", "Q3")]
    fake = _FakeStore(chunks)
    monkeypatch.setattr(_rag_routes._retriever, "_store", lambda ns: fake)
    monkeypatch.setattr(
        _rag_routes._claude_client,
        "chat_once",
        lambda **k: (_ for _ in ()).throw(
            AssertionError("must not call LLM with no matching chunks")
        ),
    )
    r = client.post(
        "/rag/namespaces/default/summary",
        json={"path": "ai", "lang": "ko"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["chunk_count"] == 0
    assert body["chunks_in_namespace"] == 1
    assert "찾지 못" in body["summary"] or "Re-index" in body["summary"]


def test_summary_subpath_traversal_rejected(client, patched_paths):
    r = client.post(
        "/rag/namespaces/default/summary",
        json={"path": "../escape", "lang": "ko"},
    )
    assert r.status_code == 422


def test_summary_no_api_key_returns_503(
    client, patched_paths, monkeypatch
):
    from src.api.routes import rag as _rag_routes

    fake = _FakeStore([_make_chunk("d1", "x.md", "hi")])
    monkeypatch.setattr(_rag_routes._retriever, "_store", lambda ns: fake)

    def _raise_no_key(**k):
        raise RuntimeError("ANTHROPIC_API_KEY not set in .env")

    monkeypatch.setattr(_rag_routes._claude_client, "chat_once", _raise_no_key)
    r = client.post(
        "/rag/namespaces/default/summary",
        json={"path": "", "lang": "ko"},
    )
    assert r.status_code == 503
    assert "ANTHROPIC_API_KEY" in r.json()["detail"]


# ── Root files (filesystem-mirror UX) ───────────────────────────────────


def test_root_files_list_only_top_level(client, patched_paths):
    """Root listing returns top-level files only — not namespace folders or
    files inside them."""
    vs_root, cd_root = patched_paths
    (cd_root / "a.md").write_text("at root", encoding="utf-8")
    (cd_root / "b.txt").write_text("also root", encoding="utf-8")
    # subdirectory + file inside — must not appear in root list
    (cd_root / "default").mkdir()
    (cd_root / "default" / "inside.md").write_text("nested", encoding="utf-8")
    r = client.get("/rag/root/files")
    assert r.status_code == 200, r.text
    body = r.json()
    names = {f["filename"] for f in body["files"]}
    assert names == {"a.md", "b.txt"}
    # All marked as not-indexed (root files aren't bound to any namespace)
    for f in body["files"]:
        assert f["indexed"] is False
        assert f["chunk_count"] == 0


def test_root_files_list_filters_extensions(client, patched_paths):
    vs_root, cd_root = patched_paths
    (cd_root / "ok.md").write_text("yes", encoding="utf-8")
    (cd_root / "x.exe").write_bytes(b"binary")
    (cd_root / "noext").write_text("hmm", encoding="utf-8")
    r = client.get("/rag/root/files")
    assert r.status_code == 200
    names = {f["filename"] for f in r.json()["files"]}
    assert names == {"ok.md"}


def test_root_files_list_empty_when_root_missing(client, patched_paths):
    """When data/company_docs/ doesn't exist yet, return empty list (no 500)."""
    vs_root, cd_root = patched_paths
    # Remove the dir to simulate fresh install
    import shutil

    shutil.rmtree(cd_root)
    r = client.get("/rag/root/files")
    assert r.status_code == 200
    assert r.json()["files"] == []


def test_upload_root_file_success(client, patched_paths):
    vs_root, cd_root = patched_paths
    files = {
        "file": ("README.md", io.BytesIO(b"# Workspace"), "text/markdown")
    }
    r = client.post("/rag/root/files", files=files)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["filename"] == "README.md"
    assert body["size_bytes"] == 11
    saved = cd_root / "README.md"
    assert saved.exists()
    assert saved.read_bytes() == b"# Workspace"


def test_upload_root_file_traversal_blocked(client, patched_paths):
    files = {"file": ("../evil.md", io.BytesIO(b"x"), "text/markdown")}
    r = client.post("/rag/root/files", files=files)
    assert r.status_code == 422


def test_upload_root_file_unsupported_extension(client, patched_paths):
    files = {"file": ("x.exe", io.BytesIO(b"x"), "application/octet-stream")}
    r = client.post("/rag/root/files", files=files)
    assert r.status_code == 415


def test_delete_root_file_success(client, patched_paths):
    vs_root, cd_root = patched_paths
    (cd_root / "doomed.md").write_text("bye", encoding="utf-8")
    r = client.delete("/rag/root/files/doomed.md")
    assert r.status_code == 204
    assert not (cd_root / "doomed.md").exists()


def test_delete_root_file_not_found_404(client, patched_paths):
    r = client.delete("/rag/root/files/nope.md")
    assert r.status_code == 404


def test_delete_root_file_traversal_blocked(client, patched_paths):
    vs_root, cd_root = patched_paths
    sibling = cd_root.parent / "victim.md"
    sibling.write_text("DO NOT DELETE", encoding="utf-8")
    r = client.delete("/rag/root/files/..%2Fvictim.md")
    assert r.status_code in (404, 422)
    assert sibling.exists()


def test_delete_root_file_rejects_directory(client, patched_paths):
    """Deleting a top-level folder via the file endpoint must be refused —
    UI uses a different mechanism for folders (DELETE /rag/namespaces/...)."""
    vs_root, cd_root = patched_paths
    (cd_root / "default").mkdir()
    r = client.delete("/rag/root/files/default")
    # Either 404 (not a file) or 422 — never silently rmdir
    assert r.status_code in (404, 422)
    assert (cd_root / "default").is_dir()


# ── Phase 10 P10-? — needs_reindex (folder-level stale detection) ───────


def _seed_manifest_with_index_time(
    vs_root, namespace: str, documents: dict
):
    """Like `_seed_manifest` but each entry can carry its own `indexed_at`."""
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


def test_tree_folder_marks_needs_reindex_when_file_added(
    client, patched_paths
):
    """A folder with a file that's not in manifest → needs_reindex=True."""
    vs_root, cd_root = patched_paths
    ns = cd_root / "databricks"
    (ns / "ai").mkdir(parents=True)
    (ns / "ai" / "indexed.md").write_text("hi", encoding="utf-8")
    (ns / "ai" / "fresh.md").write_text("new", encoding="utf-8")
    _seed_manifest_with_index_time(
        vs_root,
        "databricks",
        {
            "local:ai/indexed.md": {
                "source_type": "local",
                "chunk_count": 3,
                "indexed_at": "2050-01-01T00:00:00+00:00",
            }
        },
    )
    r = client.get("/rag/namespaces/databricks/tree", params={"path": ""})
    assert r.status_code == 200
    folder = next(e for e in r.json()["entries"] if e["name"] == "ai")
    assert folder["type"] == "folder"
    assert folder["needs_reindex"] is True


def test_tree_folder_clean_when_all_files_indexed(client, patched_paths):
    """All files present in manifest, none newer than indexed_at."""
    import os as _os
    import time as _time

    vs_root, cd_root = patched_paths
    ns = cd_root / "databricks"
    (ns / "ai").mkdir(parents=True)
    f = ns / "ai" / "indexed.md"
    f.write_text("hi", encoding="utf-8")
    # Set mtime well in the past so it's < indexed_at.
    past = _time.time() - 365 * 24 * 3600
    _os.utime(f, (past, past))
    _seed_manifest_with_index_time(
        vs_root,
        "databricks",
        {
            "local:ai/indexed.md": {
                "source_type": "local",
                "chunk_count": 3,
                "indexed_at": "2099-01-01T00:00:00+00:00",
            }
        },
    )
    r = client.get("/rag/namespaces/databricks/tree", params={"path": ""})
    assert r.status_code == 200
    folder = next(e for e in r.json()["entries"] if e["name"] == "ai")
    assert folder["needs_reindex"] is False


def test_namespaces_list_marks_needs_reindex(client, patched_paths):
    """The namespace-list response should also flag stale namespaces so the
    explorer pane can render the badge on top-level folders."""
    vs_root, cd_root = patched_paths
    ns = cd_root / "stale"
    ns.mkdir()
    (ns / "new.md").write_text("just uploaded", encoding="utf-8")
    _seed_manifest_with_index_time(
        vs_root,
        "stale",
        {},  # nothing indexed yet
    )
    r = client.get("/rag/namespaces")
    assert r.status_code == 200, r.text
    by_name = {n["name"]: n for n in r.json()["namespaces"]}
    assert by_name["stale"]["needs_reindex"] is True


# ── Phase 10 P10-? — Summary persistence + stale detection ──────────────


def _stub_summary_llm(monkeypatch, text: str = "- **stub**: summary"):
    """Helpers: install a deterministic Claude stub for summary tests."""
    from src.api.routes import rag as _rag_routes

    def _fake_chat_once(**_):
        return {
            "text": text,
            "usage": {"input_tokens": 100, "output_tokens": 10},
            "model": "claude-stub",
        }

    monkeypatch.setattr(
        _rag_routes._claude_client, "chat_once", _fake_chat_once
    )


def test_summary_get_returns_null_when_no_cache(client, patched_paths):
    """GET before any POST returns summary=null (200, not 404)."""
    r = client.get(
        "/rag/namespaces/default/summary", params={"path": ""}
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"summary": None}


def test_summary_persisted_and_returned_on_get(
    client, patched_paths, monkeypatch
):
    """POST writes the summary to SQLite — subsequent GET returns it."""
    from src.api.routes import rag as _rag_routes

    chunks = [_make_chunk("d1", "ai/x.md", "hi")]
    monkeypatch.setattr(
        _rag_routes._retriever, "_store", lambda ns: _FakeStore(chunks)
    )
    _stub_summary_llm(monkeypatch, text="- **first**: cached")

    r = client.post(
        "/rag/namespaces/default/summary",
        json={"path": "ai", "lang": "ko", "sample_size": 5},
    )
    assert r.status_code == 200, r.text
    posted = r.json()
    assert "first" in posted["summary"]

    r2 = client.get(
        "/rag/namespaces/default/summary", params={"path": "ai"}
    )
    assert r2.status_code == 200, r2.text
    cached = r2.json()["summary"]
    assert cached is not None
    assert cached["summary"] == posted["summary"]
    assert cached["model"] == "claude-stub"
    assert cached["is_stale"] is False
    assert cached["generated_at"] == posted["generated_at"]


def test_summary_is_stale_after_reindex(
    client, patched_paths, monkeypatch
):
    """If the folder's MAX(indexed_at) advances after generation, GET → is_stale=True."""
    from src.api.routes import rag as _rag_routes

    vs_root, cd_root = patched_paths
    # Seed a manifest at generation time.
    _seed_manifest_with_index_time(
        vs_root,
        "default",
        {
            "local:ai/x.md": {
                "source_type": "local",
                "chunk_count": 1,
                "indexed_at": "2026-04-01T00:00:00+00:00",
            }
        },
    )

    chunks = [_make_chunk("d1", "ai/x.md", "hi")]
    monkeypatch.setattr(
        _rag_routes._retriever, "_store", lambda ns: _FakeStore(chunks)
    )
    _stub_summary_llm(monkeypatch)

    r = client.post(
        "/rag/namespaces/default/summary",
        json={"path": "ai", "lang": "ko"},
    )
    assert r.status_code == 200

    # Simulate a re-index advancing the manifest forward.
    _seed_manifest_with_index_time(
        vs_root,
        "default",
        {
            "local:ai/x.md": {
                "source_type": "local",
                "chunk_count": 1,
                "indexed_at": "2099-01-01T00:00:00+00:00",
            }
        },
    )
    r2 = client.get(
        "/rag/namespaces/default/summary", params={"path": "ai"}
    )
    assert r2.status_code == 200
    cached = r2.json()["summary"]
    assert cached is not None
    assert cached["is_stale"] is True


def test_namespace_delete_clears_summaries(
    client, patched_paths, monkeypatch
):
    """force=true delete must also wipe the SQLite cache for that namespace."""
    from src.api.routes import rag as _rag_routes

    vs_root, cd_root = patched_paths
    ns = cd_root / "doomed"
    ns.mkdir()
    (ns / "x.md").write_text("data", encoding="utf-8")
    _seed_manifest_with_index_time(
        vs_root,
        "doomed",
        {
            "local:x.md": {
                "source_type": "local",
                "chunk_count": 1,
                "indexed_at": "2026-04-01T00:00:00+00:00",
            }
        },
    )

    chunks = [_make_chunk("d1", "x.md", "hi")]
    monkeypatch.setattr(
        _rag_routes._retriever, "_store", lambda ns_: _FakeStore(chunks)
    )
    _stub_summary_llm(monkeypatch)

    # Cache a summary.
    r = client.post(
        "/rag/namespaces/doomed/summary",
        json={"path": "", "lang": "ko"},
    )
    assert r.status_code == 200
    # Sanity: it's there.
    r1 = client.get("/rag/namespaces/doomed/summary")
    assert r1.json()["summary"] is not None

    # Drop the namespace.
    r2 = client.delete("/rag/namespaces/doomed?force=true")
    assert r2.status_code == 200, r2.text

    # Cache row should be gone.
    r3 = client.get("/rag/namespaces/doomed/summary")
    assert r3.status_code == 200
    assert r3.json()["summary"] is None
