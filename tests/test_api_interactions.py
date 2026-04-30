"""Phase 10 P10-6 — /interactions API tests.

Coverage:
- POST 201 with full + minimal payloads
- GET ?company= exact match filter
- GET ?q= LIKE search across company / raw_text / contact_role
- GET 404 / PATCH 404 / DELETE 404
- PATCH partial update (target_id null toggle)
- DELETE 204 actually removes the row
- Validation: blank company / bad kind / bad outcome 422

DO NOT rule: routes use module-attribute access via `_store`. Tests run
against a per-test SQLite DB via `API_APP_DB` env override.
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


def _create(client, **overrides):
    payload = {
        "company_name": "Stripe",
        "kind": "call",
        "occurred_at": "2026-04-30T10:00:00Z",
        "outcome": "positive",
        "raw_text": "초기 도입 의사 확인. RFP 진행 합의.",
        "contact_role": "VP Eng",
        **overrides,
    }
    return client.post("/interactions", json=payload)


def test_create_interaction_201(client):
    r = _create(client)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"] > 0
    assert body["company_name"] == "Stripe"
    assert body["kind"] == "call"
    assert body["outcome"] == "positive"
    assert body["target_id"] is None
    assert body["created_at"]


def test_create_interaction_minimal_payload(client):
    r = client.post(
        "/interactions",
        json={
            "company_name": "Acme",
            "kind": "note",
            "occurred_at": "2026-04-30",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["outcome"] is None
    assert body["raw_text"] is None


def test_create_interaction_blank_company_422(client):
    r = client.post(
        "/interactions",
        json={"company_name": "", "kind": "note", "occurred_at": "x"},
    )
    assert r.status_code == 422


def test_create_interaction_bad_kind_422(client):
    r = _create(client, kind="dance-off")
    assert r.status_code == 422


def test_create_interaction_bad_outcome_422(client):
    r = _create(client, outcome="excellent")
    assert r.status_code == 422


def test_list_interactions_filters_by_company(client):
    _create(client, company_name="Stripe")
    _create(client, company_name="Adyen")
    _create(client, company_name="Stripe", kind="meeting")

    r = client.get("/interactions?company=Stripe")
    assert r.status_code == 200
    rows = r.json()["interactions"]
    assert {row["company_name"] for row in rows} == {"Stripe"}
    assert len(rows) == 2


def test_list_interactions_q_search_across_fields(client):
    _create(client, company_name="Stripe", raw_text="lakehouse migration interest")
    _create(client, company_name="Adyen", raw_text="vendor evaluation",
            contact_role="Director — Lakehouse Lead")
    _create(client, company_name="Other", raw_text="unrelated note")

    r = client.get("/interactions?q=lakehouse")
    assert r.status_code == 200
    rows = r.json()["interactions"]
    companies = {row["company_name"] for row in rows}
    assert companies == {"Stripe", "Adyen"}


def test_list_interactions_orders_newest_first(client):
    _create(client, occurred_at="2026-04-29T10:00:00Z")
    _create(client, occurred_at="2026-04-30T10:00:00Z")
    _create(client, occurred_at="2026-04-28T10:00:00Z")
    rows = client.get("/interactions").json()["interactions"]
    assert [r["occurred_at"][:10] for r in rows] == [
        "2026-04-30",
        "2026-04-29",
        "2026-04-28",
    ]


def test_get_interaction_404(client):
    r = client.get("/interactions/9999")
    assert r.status_code == 404


def test_patch_interaction_partial_update(client):
    cid = _create(client).json()["id"]
    r = client.patch(
        f"/interactions/{cid}",
        json={"outcome": "neutral", "raw_text": "변경된 메모"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["outcome"] == "neutral"
    assert body["raw_text"] == "변경된 메모"
    # Original fields preserved
    assert body["company_name"] == "Stripe"


def test_patch_interaction_404(client):
    r = client.patch("/interactions/9999", json={"outcome": "neutral"})
    assert r.status_code == 404


def test_patch_interaction_bad_kind_422(client):
    cid = _create(client).json()["id"]
    r = client.patch(f"/interactions/{cid}", json={"kind": "shrug"})
    assert r.status_code == 422


def test_delete_interaction_204(client):
    cid = _create(client).json()["id"]
    r = client.delete(f"/interactions/{cid}")
    assert r.status_code == 204
    assert client.get(f"/interactions/{cid}").status_code == 404


def test_delete_interaction_404(client):
    r = client.delete("/interactions/9999")
    assert r.status_code == 404
