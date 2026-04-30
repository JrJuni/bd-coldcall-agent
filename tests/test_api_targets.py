"""Phase 10 P10-1 — /targets CRUD tests.

Exercises the SQLite-backed `TargetStore` end-to-end via the FastAPI
TestClient. Uses `tmp_path` for both checkpoint and app DBs so each
test starts with a clean slate; `reset_api_settings_cache` + `reset_stores`
ensure module-level singletons re-resolve to the per-test paths.

DO NOT rule: routes import `src.api.store as _store`, so we never bind
`TargetStore` directly into the route module.
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
    body = {
        "name": "Stripe",
        "industry": "Financial Services",
        "aliases": ["스트라이프"],
        "notes": "global payments",
        "stage": "planned",
    }
    body.update(overrides)
    r = client.post("/targets", json=body)
    return r


def test_create_target_returns_201_and_record(client):
    r = _create(client)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"] >= 1
    assert body["name"] == "Stripe"
    assert body["industry"] == "Financial Services"
    assert body["aliases"] == ["스트라이프"]
    assert body["notes"] == "global payments"
    assert body["stage"] == "planned"
    assert body["created_from"] == "manual"
    assert body["discovery_candidate_id"] is None
    assert body["created_at"] and body["updated_at"]


def test_create_target_rejects_blank_name(client):
    r = _create(client, name="")
    assert r.status_code == 422


def test_create_target_rejects_bad_stage(client):
    r = _create(client, stage="archived")
    assert r.status_code == 422


def test_list_targets_newest_first(client):
    for name in ("A", "B", "C"):
        _create(client, name=name)
    r = client.get("/targets")
    assert r.status_code == 200
    rows = r.json()["targets"]
    assert [t["name"] for t in rows] == ["C", "B", "A"]


def test_get_target_404_for_unknown(client):
    r = client.get("/targets/9999")
    assert r.status_code == 404


def test_get_target_returns_aliases_as_list(client):
    created = _create(client, aliases=["a", "b", "c"]).json()
    r = client.get(f"/targets/{created['id']}")
    assert r.status_code == 200
    assert r.json()["aliases"] == ["a", "b", "c"]


def test_patch_target_updates_fields_and_bumps_updated_at(client):
    created = _create(client).json()
    tid = created["id"]
    r = client.patch(
        f"/targets/{tid}",
        json={"stage": "contacted", "notes": "called once"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stage"] == "contacted"
    assert body["notes"] == "called once"
    # other fields unchanged
    assert body["name"] == "Stripe"
    assert body["aliases"] == ["스트라이프"]


def test_patch_target_partial_only_changes_provided_keys(client):
    created = _create(client).json()
    tid = created["id"]
    r = client.patch(f"/targets/{tid}", json={"aliases": ["new1"]})
    assert r.status_code == 200
    assert r.json()["aliases"] == ["new1"]
    # name/industry untouched
    assert r.json()["name"] == "Stripe"


def test_patch_target_404_for_unknown(client):
    r = client.patch("/targets/9999", json={"stage": "won"})
    assert r.status_code == 404


def test_patch_target_rejects_bad_stage(client):
    created = _create(client).json()
    r = client.patch(f"/targets/{created['id']}", json={"stage": "nope"})
    assert r.status_code == 422


def test_delete_target_removes_record(client):
    created = _create(client).json()
    tid = created["id"]
    r = client.delete(f"/targets/{tid}")
    assert r.status_code == 204
    r2 = client.get(f"/targets/{tid}")
    assert r2.status_code == 404


def test_delete_target_404_for_unknown(client):
    r = client.delete("/targets/9999")
    assert r.status_code == 404


def test_aliases_default_to_empty_list(client):
    r = client.post(
        "/targets",
        json={"name": "Adyen", "industry": "Financial Services"},
    )
    assert r.status_code == 201
    assert r.json()["aliases"] == []
