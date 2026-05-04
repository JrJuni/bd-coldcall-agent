"""Cost Explorer endpoint smoke tests."""
from __future__ import annotations

import os

os.environ["API_SKIP_WARMUP"] = "1"

import pytest
from fastapi.testclient import TestClient

from src.api import store as _store
from src.api.config import reset_api_settings_cache


@pytest.fixture
def isolated_config(monkeypatch, tmp_path):
    """Redirect loader at a tmp config dir seeded with cost yaml so PUT
    tests don't clobber the committed config/pricing.yaml."""
    cfg = tmp_path / "config"
    cfg.mkdir()
    pricing = (
        "llm:\n"
        "  claude-sonnet-4-6:\n"
        "    input_per_mtok: 3.0\n"
        "    output_per_mtok: 15.0\n"
        "    cache_read_per_mtok: 0.3\n"
        "    cache_write_per_mtok: 3.75\n"
        "  claude-haiku-4-5-20251001:\n"
        "    input_per_mtok: 1.0\n"
        "    output_per_mtok: 5.0\n"
        "    cache_read_per_mtok: 0.1\n"
        "    cache_write_per_mtok: 1.25\n"
        "search:\n"
        "  brave:\n"
        "    per_query_usd: 0.0\n"
    )
    (cfg / "pricing.yaml").write_text(pricing, encoding="utf-8")
    (cfg / "cost_budget.yaml").write_text(
        "monthly_usd: 100.0\nwarn_pct: 0.8\n", encoding="utf-8"
    )

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


def test_cost_summary_empty_store(client, isolated_config):
    r = client.get("/cost/summary?days=14")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kpi"]["this_month_usd"] == 0.0
    assert body["kpi"]["cumulative_usd"] == 0.0
    assert body["recent_runs"] == []
    assert len(body["daily_series"]) == 14
    assert body["budget"]["monthly_usd"] > 0
    assert body["budget"]["used_usd"] == 0.0
    assert body["days"] == 14


def test_cost_summary_clamps_days(client, isolated_config):
    r = client.get("/cost/summary?days=0")
    assert r.status_code == 422
    r = client.get("/cost/summary?days=400")
    assert r.status_code == 422


def test_cost_summary_picks_up_proposal_runs(client, isolated_config, monkeypatch):
    """Seed a completed run via /runs → /cost/summary reflects USD."""

    def _fake(*, run_id, company, industry, lang, top_k,
              output_root=None, checkpointer=None, store=None):
        s = store or _store.get_run_store()
        s.update(
            run_id,
            status="completed",
            usage={
                "input_tokens": 1_000_000,
                "output_tokens": 100_000,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
            ended_at="t1",
        )

    monkeypatch.setattr("src.api.runner.execute_run", _fake)

    client.post(
        "/runs", json={"company": "Acme", "industry": "fin", "lang": "en"}
    )

    body = client.get("/cost/summary?days=30").json()
    assert body["kpi"]["cumulative_usd"] > 0
    assert any(r["run_type"] == "proposal" for r in body["recent_runs"])
    proposal_row = next(
        r for r in body["recent_runs"] if r["run_type"] == "proposal"
    )
    assert proposal_row["tokens"]["input"] == 1_000_000
    assert proposal_row["usd"] > 0


def test_pricing_kind_round_trips_through_settings_put(client, isolated_config):
    r = client.get("/settings/pricing")
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "pricing"
    raw = (
        "llm:\n"
        "  claude-sonnet-4-6:\n"
        "    input_per_mtok: 5.0\n"
        "    output_per_mtok: 25.0\n"
        "    cache_read_per_mtok: 0.5\n"
        "    cache_write_per_mtok: 6.25\n"
        "search:\n"
        "  brave:\n"
        "    per_query_usd: 0.0\n"
    )
    r2 = client.put("/settings/pricing", json={"raw_yaml": raw})
    assert r2.status_code == 200, r2.text
    # Saved file is the tmp one — verify it actually got written there
    assert "5.0" in (isolated_config / "pricing.yaml").read_text()


def test_cost_budget_kind_round_trips(client, isolated_config):
    raw = "monthly_usd: 250.0\nwarn_pct: 0.7\n"
    r = client.put("/settings/cost_budget", json={"raw_yaml": raw})
    assert r.status_code == 200, r.text
    body = client.get("/cost/summary?days=30").json()
    assert body["budget"]["monthly_usd"] == 250.0
    assert body["budget"]["warn_pct"] == 0.7


def test_pricing_invalid_yaml_422(client, isolated_config):
    r = client.put(
        "/settings/pricing",
        json={"raw_yaml": "llm:\n  bogus:\n    input_per_mtok: not-a-number\n"},
    )
    assert r.status_code == 422


# ── Active-model swap ──────────────────────────────────────────────────


def _seed_settings_yaml(cfg_dir, model="claude-sonnet-4-6"):
    """Drop a minimal valid settings.yaml into the tmp config dir."""
    body = (
        "# leading comment\n"
        "llm:\n"
        "  local_model: LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct\n"
        f"  claude_model: {model}    # active model\n"
        "  quantization: 4bit\n"
        "  claude_max_tokens_synthesize: 2000\n"
        "  claude_max_tokens_draft: 4000\n"
        "  claude_max_tokens_discover: 6000\n"
        "  claude_temperature: 0.3\n"
        "  claude_rag_top_k: 8\n"
        "search:\n"
        "  default_lang: en\n"
        "  days: 30\n"
        "  max_results_per_query: 10\n"
        "  max_articles: 20\n"
        "  min_article_length: 200\n"
        "  bilingual_on_ko: true\n"
        "  min_foreign_ratio: 0.5\n"
        "  dedup_similarity_threshold: 0.9\n"
        "  min_articles_after_dedup: 10\n"
        "  fetch_workers: 5\n"
        "rag:\n"
        "  embedding_model: BAAI/bge-m3\n"
        "  chunk_size: 500\n"
        "  chunk_overlap: 50\n"
        "  top_k: 5\n"
        "  vectorstore_path: data/vectorstore\n"
        "  collection_name: bd_tech_docs\n"
        "  min_document_chars: 40\n"
        "output:\n"
        "  dir: outputs\n"
        "  intermediate: true\n"
    )
    (cfg_dir / "settings.yaml").write_text(body, encoding="utf-8")


def test_active_model_get_lists_pricing_models(client, isolated_config):
    _seed_settings_yaml(isolated_config)
    # Add one more model to pricing to verify enumeration.
    raw = (
        "llm:\n"
        "  claude-sonnet-4-6:\n"
        "    input_per_mtok: 3.0\n"
        "    output_per_mtok: 15.0\n"
        "    cache_read_per_mtok: 0.3\n"
        "    cache_write_per_mtok: 3.75\n"
        "  claude-haiku-4-5-20251001:\n"
        "    input_per_mtok: 1.0\n"
        "    output_per_mtok: 5.0\n"
        "    cache_read_per_mtok: 0.1\n"
        "    cache_write_per_mtok: 1.25\n"
        "search:\n"
        "  brave:\n"
        "    per_query_usd: 0.0\n"
    )
    client.put("/settings/pricing", json={"raw_yaml": raw})

    r = client.get("/cost/active-model")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["active"] == "claude-sonnet-4-6"
    ids = sorted(m["id"] for m in body["available"])
    assert "claude-haiku-4-5-20251001" in ids
    assert "claude-sonnet-4-6" in ids


def test_active_model_swap_preserves_comments(client, isolated_config):
    _seed_settings_yaml(isolated_config)
    r = client.post(
        "/cost/active-model",
        json={"model": "claude-haiku-4-5-20251001"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["active"] == "claude-haiku-4-5-20251001"

    new_text = (isolated_config / "settings.yaml").read_text(encoding="utf-8")
    # The leading comment + trailing comment on the swapped line are intact.
    assert "# leading comment" in new_text
    assert "# active model" in new_text
    assert "claude_model: claude-haiku-4-5-20251001" in new_text
    # Other keys untouched.
    assert "local_model: LGAI-EXAONE" in new_text
    assert "claude_temperature: 0.3" in new_text


def test_active_model_swap_rejects_unknown_model(client, isolated_config):
    _seed_settings_yaml(isolated_config)
    r = client.post(
        "/cost/active-model", json={"model": "claude-bogus-9000"}
    )
    assert r.status_code == 422


def test_cost_summary_includes_rag_summary_records(client, isolated_config):
    """Seed an rag_summaries row → /cost/summary surfaces it."""
    from src.api.config import get_api_settings
    from src.api import db as _db

    db_path = get_api_settings().app_db
    _db.init_db(db_path)
    with _db.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO rag_summaries"
            " (ws_slug, namespace, path, summary, lang, model, usage_json,"
            "  chunk_count, chunks_in_namespace, generated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "default",
                "default",
                "",
                "test summary",
                "ko",
                "claude-sonnet-4-6",
                '{"input_tokens":50000,"output_tokens":2000}',
                10,
                40,
                "2026-05-04T08:00:00+00:00",
            ),
        )

    body = client.get("/cost/summary?days=30").json()
    rag_rows = [r for r in body["recent_runs"] if r["run_type"] == "rag_summary"]
    assert len(rag_rows) == 1
    assert rag_rows[0]["tokens"]["input"] == 50000
    assert rag_rows[0]["usd"] > 0
    by_run_type = {it["label"]: it for it in body["by_run_type"]}
    assert "rag_summary" in by_run_type
