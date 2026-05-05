"""Phase 12 — /discovery metadata endpoints.

Currently covers:
  - GET /discovery/regions — country master sourced from `config/regions.yaml`
  - GET /discovery/profiles — scoring profiles from `config/weights.yaml`
  - GET /discovery/dimensions — yaml-driven scoring dimensions
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


def test_list_profiles_returns_default_first(client):
    """The /discovery/profiles endpoint always prepends an implicit
    `default` entry so a fresh user sees a no-override option even before
    config/weights.yaml has any named profiles."""
    r = client.get("/discovery/profiles")
    assert r.status_code == 200, r.text
    body = r.json()
    profiles = body["profiles"]
    assert isinstance(profiles, list)
    assert len(profiles) >= 1
    first = profiles[0]
    assert first["key"] == "default"
    assert first["is_default"] is True
    assert isinstance(first["description"], str) and first["description"]
    assert "effective_weights" in first
    assert isinstance(first["effective_weights"], dict)
    # Default profile's effective weights must sum to ~1.0 (normalized yaml).
    total = sum(float(v) for v in first["effective_weights"].values())
    assert abs(total - 1.0) < 0.02


def test_list_profiles_includes_yaml_entries(client):
    """Every key under `weights.yaml::profiles` should round-trip through
    /discovery/profiles with its description and effective_weights preserved."""
    r = client.get("/discovery/profiles")
    body = r.json()
    keys = {p["key"] for p in body["profiles"]}
    # Phase 12 ships at least one named profile (databricks).
    assert "databricks" in keys
    assert body.get("config_warning") is None
    for p in body["profiles"]:
        assert "key" in p and "label" in p
        assert "description" in p and isinstance(p["description"], str)
        assert "is_default" in p
        assert "effective_weights" in p
        assert isinstance(p["effective_weights"], dict)
        if p["key"] != "default":
            assert p["is_default"] is False
            # Each named profile's effective weights also normalize to 1.0.
            total = sum(float(v) for v in p["effective_weights"].values())
            assert abs(total - 1.0) < 0.02


def test_list_profiles_surfaces_config_warning(client, monkeypatch):
    """If `load_weights(profile)` raises for *any* profile entry, the
    endpoint still returns 200 with `effective_weights = {}` for that
    entry plus a populated `config_warning` so the UI can warn instead of
    silently shipping broken effective weights."""
    from src.api.routes import discovery as _routes

    def _broken(profile=None):
        raise ValueError("weights.yaml is malformed: missing dimension X")

    monkeypatch.setattr(_routes._scoring, "load_weights", _broken)
    r = client.get("/discovery/profiles")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["config_warning"], "config_warning must be populated"
    for p in body["profiles"]:
        assert p["effective_weights"] == {}


# ── /discovery/dimensions (Phase 12 B4a) ───────────────────────────────


def test_list_dimensions_returns_active_set(client):
    """The shipped weights.yaml ships the Phase 9.1 six-dim spine — the
    endpoint must surface every key, label, description, and default_weight."""
    r = client.get("/discovery/dimensions")
    assert r.status_code == 200, r.text
    body = r.json()
    dims = body["dimensions"]
    assert isinstance(dims, list) and len(dims) >= 1
    keys = [d["key"] for d in dims]
    for required in (
        "pain_severity", "data_complexity", "governance_need",
        "ai_maturity", "buying_trigger", "displacement_ease",
    ):
        assert required in keys, f"weights.yaml missing dimension {required!r}"
    for d in dims:
        assert isinstance(d["key"], str) and d["key"]
        assert isinstance(d["label"], str) and d["label"]
        assert isinstance(d["description"], str)
        assert isinstance(d["default_weight"], (int, float))
        assert d["default_weight"] >= 0


def test_list_dimensions_default_weights_sum_to_one(client):
    """Default weights from the shipped yaml must auto-normalize to ~1.0
    so the slider UI can seed sliders directly without further math."""
    r = client.get("/discovery/dimensions")
    body = r.json()
    total = sum(d["default_weight"] for d in body["dimensions"])
    assert abs(total - 1.0) < 0.02, f"weights don't sum to 1.0: {total}"
    # Healthy yaml → no warning surfaced.
    assert body.get("config_warning") is None


def test_list_dimensions_surfaces_config_warning(client, monkeypatch):
    """If `load_weights()` raises (yaml missing a key for a declared
    dimension), the endpoint still returns 200 + 0.0 defaults but flags
    the issue via `config_warning` so the UI can show a banner instead of
    silently rendering broken sliders."""
    from src.api.routes import discovery as _routes

    def _broken():
        raise ValueError(
            "weights for profile=None missing dimensions: ['budget_authority']"
        )

    monkeypatch.setattr(_routes._scoring, "load_weights", _broken)
    r = client.get("/discovery/dimensions")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["config_warning"], "config_warning must be populated on bad yaml"
    assert "missing dimensions" in body["config_warning"]
    # Sliders still render (UI doesn't 500), all weights at 0.0.
    assert all(d["default_weight"] == 0.0 for d in body["dimensions"])
