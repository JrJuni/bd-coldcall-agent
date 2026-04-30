"""Phase 10 P10-5 — Daily News API tests.

Coverage:
- POST /news/refresh queues a task and module-attr-monkeypatched runner
  populates the row to status=completed
- GET  /news/today returns the latest completed row, 404 when empty
- GET  /news/runs/{task_id} returns the row or 404
- Validation rejects blank seed_query / invalid namespace
- Failed runs surface error_message
- DO NOT rule: monkeypatch happens at module attribute, never via
  ``from src.api.runner import execute_news_refresh``.
"""
from __future__ import annotations

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


def _fake_runner(status: str = "completed", articles: list[dict] | None = None):
    articles = articles or [
        {
            "title": "Databricks Q4",
            "url": "https://example.com/a",
            "snippet": "Numbers go up.",
            "hostname": "example.com",
            "lang": "en",
            "published": "2026-04-29T10:00:00+00:00",
        },
        {
            "title": "Snowflake Earnings",
            "url": "https://example.com/b",
            "snippet": "Cloud DW commentary.",
            "hostname": "example.com",
            "lang": "en",
            "published": None,
        },
    ]

    def _fake(*, task_id, namespace, seed_query, lang, days, count, **kw):
        store = _store.get_news_store()
        store.update(task_id, status="running", started_at="t0")
        if status == "failed":
            store.update(
                task_id,
                status="failed",
                ended_at="t1",
                error_message="Brave 401",
            )
            return
        store.update(
            task_id,
            status="completed",
            ended_at="t1",
            articles=articles,
            article_count=len(articles),
        )

    return _fake


def test_refresh_news_queues_and_runner_completes(client, monkeypatch):
    monkeypatch.setattr("src.api.runner.execute_news_refresh", _fake_runner())
    r = client.post(
        "/news/refresh",
        json={"namespace": "databricks", "seed_query": "AI infra", "lang": "en"},
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "queued"
    assert body["namespace"] == "databricks"
    task_id = body["task_id"]
    assert task_id.startswith("news-")

    detail = client.get(f"/news/runs/{task_id}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["status"] == "completed"
    assert payload["article_count"] == 2
    assert len(payload["articles"]) == 2
    assert payload["articles"][0]["title"] == "Databricks Q4"


def test_news_today_returns_latest_completed(client, monkeypatch):
    monkeypatch.setattr("src.api.runner.execute_news_refresh", _fake_runner())
    client.post(
        "/news/refresh",
        json={"namespace": "default", "seed_query": "AI infra", "lang": "en"},
    )
    r = client.get("/news/today?namespace=default")
    assert r.status_code == 200
    body = r.json()
    assert body["namespace"] == "default"
    assert body["status"] == "completed"
    assert len(body["articles"]) == 2


def test_news_today_404_when_empty(client):
    r = client.get("/news/today?namespace=default")
    assert r.status_code == 404


def test_get_news_run_404(client):
    r = client.get("/news/runs/news-doesnt-exist")
    assert r.status_code == 404


def test_refresh_news_rejects_blank_query(client):
    r = client.post(
        "/news/refresh",
        json={"namespace": "default", "seed_query": "", "lang": "en"},
    )
    assert r.status_code == 422


def test_refresh_news_rejects_invalid_namespace(client):
    r = client.post(
        "/news/refresh",
        json={"namespace": "bad name!", "seed_query": "AI", "lang": "en"},
    )
    assert r.status_code == 422


def test_refresh_news_failed_status_surfaces_error(client, monkeypatch):
    monkeypatch.setattr(
        "src.api.runner.execute_news_refresh", _fake_runner(status="failed")
    )
    r = client.post(
        "/news/refresh",
        json={"namespace": "default", "seed_query": "AI", "lang": "en"},
    )
    task_id = r.json()["task_id"]
    detail = client.get(f"/news/runs/{task_id}").json()
    assert detail["status"] == "failed"
    assert detail["error_message"] == "Brave 401"
    # /news/today filters to completed only — failed should be hidden
    today = client.get("/news/today?namespace=default")
    assert today.status_code == 404


def test_list_news_runs_newest_first(client, monkeypatch):
    monkeypatch.setattr("src.api.runner.execute_news_refresh", _fake_runner())
    for _ in range(3):
        client.post(
            "/news/refresh",
            json={"namespace": "default", "seed_query": "AI", "lang": "en"},
        )
    r = client.get("/news/runs?namespace=default")
    assert r.status_code == 200
    runs = r.json()["runs"]
    assert len(runs) == 3
    timestamps = [run["generated_at"] for run in runs]
    assert timestamps == sorted(timestamps, reverse=True)


def test_refresh_news_filters_by_namespace(client, monkeypatch):
    monkeypatch.setattr("src.api.runner.execute_news_refresh", _fake_runner())
    client.post(
        "/news/refresh",
        json={"namespace": "databricks", "seed_query": "AI", "lang": "en"},
    )
    client.post(
        "/news/refresh",
        json={"namespace": "snowflake", "seed_query": "AI", "lang": "en"},
    )
    r = client.get("/news/today?namespace=databricks")
    assert r.status_code == 200
    assert r.json()["namespace"] == "databricks"
    r2 = client.get("/news/today?namespace=other")
    assert r2.status_code == 404
