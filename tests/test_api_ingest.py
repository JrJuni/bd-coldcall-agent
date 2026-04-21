"""Phase 7 — /ingest endpoint tests.

Uses the same module-attribute patch pattern as /runs. The indexer is
stubbed out so tests don't touch ChromaDB.
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


def test_ingest_status_no_manifest(client, monkeypatch, tmp_path):
    # Point settings at a directory without a manifest
    monkeypatch.setenv("API_SKIP_WARMUP", "1")

    # Patch get_settings to use a tmp vectorstore path
    from src.config import loader as _loader
    original = _loader.get_settings()

    class _FakeRag:
        vectorstore_path = tmp_path / "empty_vs"
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

    from src.api.routes import ingest as _ingest_routes
    monkeypatch.setattr(_ingest_routes._config_loader, "get_settings", lambda: _FakeSettings())

    r = client.get("/ingest/status")
    assert r.status_code == 200
    body = r.json()
    assert body["manifest_exists"] is False
    assert body["document_count"] == 0


def test_ingest_status_reads_manifest(client, monkeypatch, tmp_path):
    vs_dir = tmp_path / "vs"
    vs_dir.mkdir()
    manifest = {
        "version": 1,
        "updated_at": "2026-04-22T00:00:00+00:00",
        "documents": {
            "doc_a": {"source_type": "local_file", "chunk_count": 3},
            "doc_b": {"source_type": "local_file", "chunk_count": 5},
            "doc_c": {"source_type": "notion", "chunk_count": 2},
        },
    }
    (vs_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

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

    from src.api.routes import ingest as _ingest_routes
    monkeypatch.setattr(_ingest_routes._config_loader, "get_settings", lambda: _FakeSettings())

    r = client.get("/ingest/status")
    assert r.status_code == 200
    body = r.json()
    assert body["manifest_exists"] is True
    assert body["version"] == 1
    assert body["document_count"] == 3
    assert body["chunk_count"] == 10
    assert body["by_source_type"] == {"local_file": 2, "notion": 1}


def test_trigger_ingest_queues_task_and_tracks_status(client, monkeypatch):
    captured: dict = {}

    def _fake_execute_ingest(*, task_id, params, store=None):
        captured["task_id"] = task_id
        captured["params"] = dict(params)
        s = store or _store.get_ingest_store()
        s.update(task_id, status="completed", ended_at="t1", message="done")

    monkeypatch.setattr("src.api.runner.execute_ingest", _fake_execute_ingest)

    r = client.post("/ingest", json={"notion": True, "dry_run": True})
    assert r.status_code == 202, r.text
    task_id = r.json()["task_id"]
    assert captured["task_id"] == task_id
    assert captured["params"]["notion"] is True
    assert captured["params"]["dry_run"] is True

    r2 = client.get(f"/ingest/tasks/{task_id}")
    assert r2.status_code == 200
    assert r2.json()["status"] == "completed"


def test_ingest_task_404_for_unknown(client):
    r = client.get("/ingest/tasks/nope")
    assert r.status_code == 404
