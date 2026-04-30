"""Phase 10 P10-2a — /rag/namespaces tests.

Verifies:
- Empty vectorstore → still surfaces `default` (so the dropdown is never empty)
- Multiple namespaces with manifests → returned with counts/by_source_type
- `is_default` flag set correctly
- Module-attribute monkeypatch only (DO NOT rule)
"""
from __future__ import annotations

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


def _patch_settings(monkeypatch, vs_dir):
    """Make both rag.py and ingest.py see a tmp vectorstore root."""
    from src.config import loader as _loader

    original = _loader.get_settings()

    class _FakeRag:
        vectorstore_path = vs_dir
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

    from src.api.routes import rag as _rag_routes

    monkeypatch.setattr(
        _rag_routes._config_loader, "get_settings", lambda: _FakeSettings()
    )


def test_rag_namespaces_empty_returns_default_only(client, monkeypatch, tmp_path):
    vs_dir = tmp_path / "vs"
    _patch_settings(monkeypatch, vs_dir)
    r = client.get("/rag/namespaces")
    assert r.status_code == 200
    body = r.json()
    assert body["default"] == "default"
    names = [ns["name"] for ns in body["namespaces"]]
    assert names == ["default"]
    only = body["namespaces"][0]
    assert only["is_default"] is True
    assert only["document_count"] == 0
    assert only["chunk_count"] == 0


def test_rag_namespaces_lists_each_with_metadata(client, monkeypatch, tmp_path):
    vs_dir = tmp_path / "vs"
    # Seed two namespaces with manifests
    for ns, docs in [
        ("default", {"a": {"source_type": "local_file", "chunk_count": 3}}),
        (
            "databricks",
            {
                "x": {"source_type": "local_file", "chunk_count": 5},
                "y": {"source_type": "notion", "chunk_count": 2},
            },
        ),
    ]:
        ns_dir = vs_dir / ns
        ns_dir.mkdir(parents=True)
        manifest = {
            "version": 1,
            "updated_at": "2026-04-30T00:00:00+00:00",
            "documents": docs,
        }
        (ns_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )

    _patch_settings(monkeypatch, vs_dir)
    r = client.get("/rag/namespaces")
    assert r.status_code == 200
    body = r.json()
    names = sorted(ns["name"] for ns in body["namespaces"])
    assert names == ["databricks", "default"]
    by_name = {ns["name"]: ns for ns in body["namespaces"]}
    assert by_name["default"]["is_default"] is True
    assert by_name["databricks"]["is_default"] is False
    assert by_name["databricks"]["document_count"] == 2
    assert by_name["databricks"]["chunk_count"] == 7
    assert by_name["databricks"]["by_source_type"] == {
        "local_file": 1,
        "notion": 1,
    }
    assert by_name["default"]["chunk_count"] == 3


def test_rag_namespaces_default_inserted_when_only_others_exist(
    client, monkeypatch, tmp_path
):
    """Even with only `databricks` indexed, `default` shows up so the
    Discovery dropdown always has it as a fallback."""
    vs_dir = tmp_path / "vs"
    db_dir = vs_dir / "databricks"
    db_dir.mkdir(parents=True)
    (db_dir / "manifest.json").write_text(
        json.dumps({"version": 1, "documents": {}}), encoding="utf-8"
    )

    _patch_settings(monkeypatch, vs_dir)
    r = client.get("/rag/namespaces")
    assert r.status_code == 200
    names = [ns["name"] for ns in r.json()["namespaces"]]
    assert "default" in names
    assert "databricks" in names
