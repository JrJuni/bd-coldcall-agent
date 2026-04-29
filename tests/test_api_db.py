"""Phase 10 — app.db schema + connection helper tests."""
from __future__ import annotations

import sqlite3

import pytest

from src.api import db as _db


def test_init_db_creates_all_tables(tmp_path):
    db_path = tmp_path / "app.db"
    _db.init_db(db_path)
    with _db.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    names = {r["name"] for r in rows}
    for tbl in _db.SCHEMA_TABLES:
        assert tbl in names, f"missing table {tbl}"


def test_init_db_idempotent(tmp_path):
    db_path = tmp_path / "app.db"
    _db.init_db(db_path)
    _db.init_db(db_path)  # second call must not raise
    _db.init_db(db_path)


def test_init_db_creates_parent_dir(tmp_path):
    db_path = tmp_path / "nested" / "deeper" / "app.db"
    _db.init_db(db_path)
    assert db_path.exists()


def test_connect_row_factory_and_fk_on(tmp_path):
    db_path = tmp_path / "app.db"
    _db.init_db(db_path)
    with _db.connect(db_path) as conn:
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1
        # row_factory yields sqlite3.Row (dict-like access)
        row = conn.execute(
            "SELECT 1 AS one, 2 AS two"
        ).fetchone()
        assert row["one"] == 1 and row["two"] == 2


def test_connect_commits_on_clean_exit(tmp_path):
    db_path = tmp_path / "app.db"
    _db.init_db(db_path)
    with _db.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO targets(name, industry, stage, created_from, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            ("Stripe", "Financial Services", "planned", "manual", "t", "t"),
        )
    with _db.connect(db_path) as conn:
        n = conn.execute("SELECT COUNT(*) FROM targets").fetchone()[0]
    assert n == 1


def test_connect_rolls_back_on_exception(tmp_path):
    db_path = tmp_path / "app.db"
    _db.init_db(db_path)
    with pytest.raises(RuntimeError):
        with _db.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO targets(name, industry, stage, created_from, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?)",
                ("Adyen", "Financial Services", "planned", "manual", "t", "t"),
            )
            raise RuntimeError("boom")
    with _db.connect(db_path) as conn:
        n = conn.execute("SELECT COUNT(*) FROM targets").fetchone()[0]
    assert n == 0


def test_fk_cascade_discovery_run_to_candidates(tmp_path):
    db_path = tmp_path / "app.db"
    _db.init_db(db_path)
    with _db.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO discovery_runs(run_id, generated_at, created_at) VALUES (?,?,?)",
            ("r1", "t", "t"),
        )
        conn.execute(
            "INSERT INTO discovery_candidates"
            "(run_id, name, industry, scores_json, final_score, tier, updated_at)"
            " VALUES (?,?,?,?,?,?,?)",
            ("r1", "Stripe", "Financial Services", "{}", 8.0, "S", "t"),
        )
    # cascade delete
    with _db.connect(db_path) as conn:
        conn.execute("DELETE FROM discovery_runs WHERE run_id=?", ("r1",))
    with _db.connect(db_path) as conn:
        n = conn.execute("SELECT COUNT(*) FROM discovery_candidates").fetchone()[0]
    assert n == 0


def test_fk_set_null_target_on_candidate_delete(tmp_path):
    db_path = tmp_path / "app.db"
    _db.init_db(db_path)
    with _db.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO discovery_runs(run_id, generated_at, created_at) VALUES (?,?,?)",
            ("r1", "t", "t"),
        )
        cur = conn.execute(
            "INSERT INTO discovery_candidates"
            "(run_id, name, industry, scores_json, final_score, tier, updated_at)"
            " VALUES (?,?,?,?,?,?,?)",
            ("r1", "Stripe", "Financial Services", "{}", 8.0, "S", "t"),
        )
        cand_id = cur.lastrowid
        conn.execute(
            "INSERT INTO targets(name, industry, stage, created_from,"
            " discovery_candidate_id, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?)",
            ("Stripe", "Financial Services", "planned", "discovery_promote",
             cand_id, "t", "t"),
        )
        conn.execute("DELETE FROM discovery_candidates WHERE id=?", (cand_id,))
    with _db.connect(db_path) as conn:
        row = conn.execute(
            "SELECT discovery_candidate_id FROM targets WHERE name='Stripe'"
        ).fetchone()
    assert row["discovery_candidate_id"] is None


def test_lifespan_initializes_app_db(tmp_path, monkeypatch):
    """End-to-end: creating the FastAPI app should create app.db with all tables."""
    monkeypatch.setenv("API_SKIP_WARMUP", "1")
    monkeypatch.setenv("API_CHECKPOINT_DB", str(tmp_path / "ck.db"))
    monkeypatch.setenv("API_APP_DB", str(tmp_path / "app.db"))

    from src.api.config import reset_api_settings_cache
    reset_api_settings_cache()

    from fastapi.testclient import TestClient
    from src.api.app import create_app

    app = create_app()
    with TestClient(app) as client:
        r = client.get("/healthz")
        assert r.status_code == 200

    db_path = tmp_path / "app.db"
    assert db_path.exists()
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        names = {r[0] for r in rows}
        for tbl in _db.SCHEMA_TABLES:
            assert tbl in names
    finally:
        conn.close()

    reset_api_settings_cache()
