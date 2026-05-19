"""Phase M / M2 — TestClient(create_app()) smoke for /meetings + /semantic.

These tests prove the router is actually wired into the production app
(not a side-app), and that requests reach a working repository against
a fresh schema. The LLM is stubbed out; assertions are on structural
fields only (status, source_type, evidence presence, action-item shape,
relationship shape) — no LLM-prose comparisons.
"""
from __future__ import annotations

import os

os.environ["API_SKIP_WARMUP"] = "1"

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool

import src.api.orm as _orm
from src.api import store as _store
from src.api.config import reset_api_settings_cache
from src.api.orm import Base, make_session_factory
from src.llm import meeting_analysis as ma
from tests.meeting_intelligence_samples import sample_analysis, sample_summary


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch, tmp_path):
    """Mirror tests/test_api_workspaces.py — sandbox app DB + skip warmup."""
    monkeypatch.setenv("API_SKIP_WARMUP", "1")
    monkeypatch.setenv("API_CHECKPOINT_DB", str(tmp_path / "ck.db"))
    monkeypatch.setenv("API_APP_DB", str(tmp_path / "app.db"))
    reset_api_settings_cache()
    _store.reset_stores()
    yield
    reset_api_settings_cache()
    _store.reset_stores()


@pytest.fixture
def client(monkeypatch):
    """`TestClient(create_app())` with the meeting router landing on a
    private :memory: SQLite (StaticPool — single connection across TestClient
    worker threads). LLM is stubbed."""
    engine = sa.create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )

    @sa.event.listens_for(engine, "connect")
    def _enable_sqlite_fk(dbapi_connection, _conn_record):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys = ON")
        finally:
            cursor.close()

    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    monkeypatch.setattr(_orm, "get_session_factory", lambda *a, **k: factory)

    monkeypatch.setattr(
        ma,
        "analyze_meeting_summary",
        lambda *args, **kwargs: (sample_analysis(), {}, "test-model"),
    )

    from src.api.app import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


def test_analyze_route_persists_meeting(client):
    resp = client.post(
        "/meetings/analyze",
        json={"company_name": "Acme", "summary": sample_summary(), "lang": "en"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "completed"
    meeting_id = body["meeting_id"]
    assert isinstance(meeting_id, int) and meeting_id > 0

    meeting = body["meeting"]
    assert meeting["source_type"] == "summary"
    assert meeting["summary"] == sample_summary()
    assert meeting["action_items"][0]["status"] == "open"
    assert meeting["action_items"][0]["evidence_text"]
    # Relationship rows must carry the event provenance we agreed on.
    assert all(rel["source_event_id"] for rel in meeting["relationships"])


def test_analyze_rejects_transcript_field(client):
    resp = client.post(
        "/meetings/analyze",
        json={
            "company_name": "Acme",
            "summary": sample_summary(),
            "transcript": "raw transcript is out of scope",
        },
    )
    assert resp.status_code == 422


def test_analyze_rejects_empty_company_name(client):
    resp = client.post(
        "/meetings/analyze",
        json={"company_name": "", "summary": sample_summary()},
    )
    assert resp.status_code == 422


def test_get_meeting_and_recent(client):
    created = client.post(
        "/meetings/analyze",
        json={"company_name": "Acme", "summary": sample_summary()},
    ).json()
    meeting_id = created["meeting_id"]

    detail = client.get(f"/meetings/{meeting_id}")
    assert detail.status_code == 200
    assert detail.json()["meeting"]["summary"] == sample_summary()

    brief = client.get(f"/semantic/meetings/{meeting_id}/brief")
    assert brief.status_code == 200
    assert brief.json()["meeting"]["id"] == meeting_id

    recent = client.get("/semantic/meetings/recent?limit=5")
    assert recent.status_code == 200
    rows = recent.json()["meetings"]
    assert len(rows) == 1
    assert rows[0]["company_name"] == "Acme"


def test_get_meeting_404_for_unknown_id(client):
    resp = client.get("/meetings/99999")
    assert resp.status_code == 404


def test_semantic_aggregations(client):
    client.post(
        "/meetings/analyze",
        json={"company_name": "Acme", "summary": sample_summary()},
    )

    open_items = client.get("/semantic/action-items/open").json()["items"]
    assert open_items, "stub fixture seeds at least one open action item"
    assert open_items[0]["company_name"] == "Acme"

    feedback = client.get("/semantic/product-feedback/candidates").json()["items"]
    assert any(item["type"] == "product_feedback" for item in feedback)

    objections = client.get("/semantic/objections/by_category").json()["items"]
    assert any(o["category"] == "integration" for o in objections)

    topics = client.get("/semantic/topics/top").json()["items"]
    assert topics, "topics endpoint returned at least one row"
