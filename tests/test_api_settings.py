"""Phase 10 P10-7 — /settings API tests.

Coverage:
- GET /settings lists supported kinds
- GET /settings/{kind} returns raw + parsed for existing files
- GET /settings/{kind} reports exists=False for absent files (e.g.
  competitors.yaml on a fresh checkout)
- PUT /settings/{kind} writes valid yaml, invalidates loader cache,
  returns updated parsed dict
- PUT bad YAML → 422
- PUT pydantic-invalid → 422
- GET /settings/secrets returns boolean view (never the actual values)
- Unknown kind → 404
"""
from __future__ import annotations

import os

os.environ["API_SKIP_WARMUP"] = "1"

import pytest
from fastapi.testclient import TestClient

from src.api import store as _store
from src.api.config import reset_api_settings_cache


@pytest.fixture
def isolated_config(monkeypatch, tmp_path):
    """Redirect routes/settings.py at a tmp config dir and seed a couple
    of yaml files so GET tests hit non-empty bodies."""
    cfg = tmp_path / "config"
    cfg.mkdir()
    weights = (
        "version: 1\n"
        "default:\n"
        "  pain_severity: 0.5\n"
        "  data_complexity: 0.5\n"
        "products: {}\n"
    )
    (cfg / "weights.yaml").write_text(weights, encoding="utf-8")
    tier_rules = (
        "version: 1\n"
        "tiers:\n"
        "  S: 8.0\n"
        "  A: 7.0\n"
        "  B: 6.0\n"
        "  C: 5.0\n"
    )
    (cfg / "tier_rules.yaml").write_text(tier_rules, encoding="utf-8")

    from src.config import loader as _loader

    monkeypatch.setattr(_loader, "CONFIG_DIR", cfg)
    return cfg


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


def test_list_settings_kinds(client, isolated_config):
    r = client.get("/settings")
    assert r.status_code == 200
    body = r.json()
    assert "settings" in body["kinds"]
    assert "weights" in body["kinds"]
    assert "tier_rules" in body["kinds"]


def test_get_settings_returns_raw_and_parsed(client, isolated_config):
    r = client.get("/settings/weights")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "weights"
    assert body["exists"] is True
    assert "pain_severity" in body["raw_yaml"]
    assert body["parsed"]["default"]["pain_severity"] == 0.5


def test_get_settings_missing_file_returns_exists_false(client, isolated_config):
    # competitors.yaml not seeded
    r = client.get("/settings/competitors")
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is False
    assert body["raw_yaml"] == ""
    assert body["parsed"] is None


def test_get_settings_unknown_kind_404(client, isolated_config):
    r = client.get("/settings/banana")
    assert r.status_code == 404


def test_put_settings_writes_valid_yaml(client, isolated_config):
    new_yaml = (
        "version: 1\n"
        "tiers:\n"
        "  S: 9.0\n"
        "  A: 7.5\n"
        "  B: 6.0\n"
        "  C: 4.0\n"
    )
    r = client.put("/settings/tier_rules", json={"raw_yaml": new_yaml})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["parsed"]["tiers"]["S"] == 9.0

    # Round-trip: file actually written
    r2 = client.get("/settings/tier_rules")
    assert r2.json()["parsed"]["tiers"]["S"] == 9.0


def test_put_settings_invalid_yaml_422(client, isolated_config):
    r = client.put(
        "/settings/tier_rules", json={"raw_yaml": ":\n:\n: invalid"}
    )
    assert r.status_code == 422
    assert "YAML" in r.json()["detail"] or "parse" in r.json()["detail"].lower()


def test_put_settings_top_level_not_mapping_422(client, isolated_config):
    # YAML parses to a list, not a dict
    r = client.put(
        "/settings/tier_rules", json={"raw_yaml": "- one\n- two\n"}
    )
    assert r.status_code == 422


def test_put_settings_pydantic_validation_422(client, isolated_config):
    # `tiers` must be a dict[str, float]; passing a list breaks the schema.
    r = client.put(
        "/settings/tier_rules",
        json={"raw_yaml": "version: 1\ntiers:\n  - 1\n  - 2\n"},
    )
    assert r.status_code == 422
    assert "validation" in r.json()["detail"].lower()


def test_put_settings_unknown_kind_404(client, isolated_config):
    r = client.put("/settings/banana", json={"raw_yaml": "{}"})
    assert r.status_code == 404


def test_get_secrets_returns_boolean_only(client, isolated_config, monkeypatch):
    # Force a known state via module-attr monkeypatch — .env on disk
    # would otherwise win over pydantic-settings env precedence.
    from src.api.routes import settings as _settings_routes

    class _Fake:
        anthropic_api_key = "sk-secret-value"
        brave_search_api_key = ""
        notion_token = ""

    monkeypatch.setattr(
        _settings_routes._config_loader, "get_secrets", lambda: _Fake()
    )

    r = client.get("/settings/secrets")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["anthropic_api_key"], bool)
    assert body["anthropic_api_key"] is True
    assert body["brave_search_api_key"] is False
    assert body["notion_token"] is False
    # Never echo the actual key
    assert "sk-secret-value" not in r.text
