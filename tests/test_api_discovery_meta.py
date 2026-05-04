"""Phase 12 — /discovery metadata endpoints.

Currently covers:
  - GET /discovery/regions — country master sourced from `config/regions.yaml`
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


def test_list_regions_returns_groups_and_countries(client):
    r = client.get("/discovery/regions")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"] == 1
    assert isinstance(body["groups"], list)
    assert len(body["groups"]) >= 4  # NA / Asia / Europe / Oceania at minimum

    # Every country must be a 2-letter ISO alpha-2 (lowercase) plus a label.
    for g in body["groups"]:
        assert "id" in g and "label" in g and "countries" in g
        for c in g["countries"]:
            assert isinstance(c["code"], str) and len(c["code"]) == 2
            assert c["code"] == c["code"].lower()
            assert isinstance(c["label"], str) and c["label"]


def test_list_regions_contains_anchor_countries(client):
    """The shipped regions.yaml must keep a stable spine — losing one of
    these would silently break a re-tagged sector_leaders.yaml entry."""
    r = client.get("/discovery/regions")
    body = r.json()
    flat = {c["code"] for g in body["groups"] for c in g["countries"]}
    for required in ("us", "kr", "jp", "gb", "de", "nl", "au"):
        assert required in flat, f"regions.yaml is missing anchor country {required!r}"
