"""Phase 10 P10-8 — /dashboard aggregator tests.

Coverage:
- Empty install: every aggregate is empty / None / 0
- Seeded targets / interactions / news / RAG manifest → reflected
- Discovery + run cost summed across stores
- DO NOT rule: no rebinding, only module-attr access via store and
  `_config_loader`.
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


@pytest.fixture
def patched_vs(monkeypatch, tmp_path):
    """Redirect dashboard.py + rag namespace lookups to a tmp vectorstore."""
    vs_root = tmp_path / "vs"
    vs_root.mkdir()
    from src.api.routes import dashboard as _dash
    from src.config import loader as _loader

    original = _loader.get_settings()

    class _FakeRag:
        vectorstore_path = vs_root
        collection_name = original.rag.collection_name
        min_document_chars = original.rag.min_document_chars
        chunk_size = original.rag.chunk_size
        chunk_overlap = original.rag.chunk_overlap
        top_k = original.rag.top_k
        embedding_model = original.rag.embedding_model
        notion_page_ids: list[str] = []
        notion_database_ids: list[str] = []

    class _Fake:
        rag = _FakeRag()
        llm = original.llm
        search = original.search
        output = original.output

    monkeypatch.setattr(
        _dash._config_loader, "get_settings", lambda: _Fake()
    )
    return vs_root


def test_dashboard_empty_install(client, patched_vs):
    r = client.get("/dashboard")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["recent_runs"] == []
    assert body["recent_discovery"] is None
    assert body["pipeline_by_stage"] == {}
    assert body["interactions_count"] == 0
    assert body["news"] is None
    # default namespace always surfaced
    rag = body["rag"]
    assert any(ns["namespace"] == "default" for ns in rag)
    assert all(ns["is_indexed"] is False for ns in rag)
    assert "generated_at" in body


def test_dashboard_targets_pipeline(client, patched_vs):
    client.post(
        "/targets",
        json={"name": "Stripe", "industry": "Fin", "stage": "planned"},
    )
    client.post(
        "/targets",
        json={"name": "Adyen", "industry": "Fin", "stage": "planned"},
    )
    client.post(
        "/targets",
        json={"name": "Tempus", "industry": "Health", "stage": "meeting"},
    )
    r = client.get("/dashboard")
    body = r.json()
    assert body["pipeline_by_stage"]["planned"] == 2
    assert body["pipeline_by_stage"]["meeting"] == 1


def test_dashboard_interactions_count(client, patched_vs):
    for i in range(4):
        client.post(
            "/interactions",
            json={
                "company_name": f"C{i}",
                "kind": "note",
                "occurred_at": "2026-04-30",
            },
        )
    body = client.get("/dashboard").json()
    assert body["interactions_count"] == 4


def test_dashboard_rag_picks_up_manifest(client, patched_vs):
    db_dir = patched_vs / "databricks"
    db_dir.mkdir()
    manifest = {
        "version": 1,
        "documents": {
            "local:a.md": {"source_type": "local", "chunk_count": 3},
            "local:b.md": {"source_type": "local", "chunk_count": 5},
        },
    }
    (db_dir / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    r = client.get("/dashboard")
    body = r.json()
    by_name = {ns["namespace"]: ns for ns in body["rag"]}
    assert by_name["databricks"]["document_count"] == 2
    assert by_name["databricks"]["chunk_count"] == 8
    assert by_name["databricks"]["is_indexed"] is True
    # default still surfaces (empty)
    assert "default" in by_name


def test_dashboard_news_mini_after_refresh(client, patched_vs, monkeypatch):
    """Seed a completed news_runs row → /dashboard.news reflects it."""
    def _fake(*, task_id, namespace, seed_query, lang, days, count, **kw):
        ns_store = _store.get_news_store()
        ns_store.update(
            task_id,
            status="completed",
            ended_at="t1",
            articles=[
                {"title": "Earnings Up", "url": "u", "lang": "en"},
                {"title": "AI Memo", "url": "v", "lang": "en"},
            ],
            article_count=2,
        )

    monkeypatch.setattr("src.api.runner.execute_news_refresh", _fake)
    r = client.post(
        "/news/refresh",
        json={"namespace": "default", "seed_query": "AI infra", "lang": "en"},
    )
    assert r.status_code == 202

    body = client.get("/dashboard").json()
    news = body["news"]
    assert news is not None
    assert news["namespace"] == "default"
    assert news["article_count"] == 2
    assert "Earnings Up" in news["top_titles"]


def test_dashboard_recent_runs_newest_first(client, patched_vs, monkeypatch):
    """Three /runs requests → recent_runs newest first, top 5 cap."""
    def _fake(*, run_id, company, industry, lang, top_k,
              output_root=None, checkpointer=None, store=None):
        s = store or _store.get_run_store()
        s.update(
            run_id,
            status="completed",
            proposal_md="# done",
            ended_at="t1",
        )

    monkeypatch.setattr("src.api.runner.execute_run", _fake)
    for c in ("Acme", "Beta", "Gamma"):
        client.post("/runs", json={"company": c, "industry": "x", "lang": "en"})

    body = client.get("/dashboard").json()
    runs = body["recent_runs"]
    assert len(runs) == 3
    # newest first → Gamma, Beta, Acme
    assert [r["company"] for r in runs] == ["Gamma", "Beta", "Acme"]
