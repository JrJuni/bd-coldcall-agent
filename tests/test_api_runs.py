"""Phase 7 — /runs endpoint tests.

TestClient dispatches BackgroundTasks synchronously after the response
is returned, so by the time `.post()` returns the run has typically
finished. We monkeypatch `src.api.runner.execute_run` with a fake that
mutates the RunStore deterministically — the real orchestrator requires
Brave / Exaone / Sonnet and is out of scope for unit tests.

DO NOT rule compliance: we patch module-attribute access (`src.api.runner
.execute_run`), not a from-imported binding.
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


def _fake_execute_run_factory(status: str = "completed", stages: list[str] | None = None):
    stages = stages or [
        "search", "fetch", "preprocess",
        "retrieve", "synthesize", "draft", "persist",
    ]

    def _fake(*, run_id: str, company: str, industry: str, lang: str,
              top_k, output_root=None, checkpointer=None, store=None):
        s = store or _store.get_run_store()
        record = s.get(run_id)
        assert record is not None
        s.update(run_id, status="running", started_at="t0")
        record.append_event("run_started", {"run_id": run_id})
        for stage in stages:
            record.append_event("stage_started", {"stage": stage})
            record.append_event("stage_completed", {"stage": stage})
            s.update(
                run_id,
                current_stage=stage,
                stages_completed=list(record.stages_completed) + [stage],
            )
        failed = status == "failed"
        s.update(
            run_id,
            status=status,
            proposal_md="# done" if not failed else None,
            ended_at="t1",
            duration_s=0.1,
            failed_stage="draft" if failed else None,
        )
        record.append_event(
            "run_completed" if not failed else "run_failed",
            {"status": status, "failed_stage": "draft" if failed else None},
        )

    return _fake


def test_healthz_reports_warmup_skipped(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["warmup_skipped"] is True
    assert body["exaone_loaded"] is False


def test_create_run_returns_run_id_and_persists_record(client, monkeypatch):
    monkeypatch.setattr("src.api.runner.execute_run", _fake_execute_run_factory())

    r = client.post(
        "/runs",
        json={"company": "NVIDIA", "industry": "semiconductor", "lang": "en"},
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["run_id"].endswith("-NVIDIA")
    run_id = body["run_id"]

    r2 = client.get(f"/runs/{run_id}")
    assert r2.status_code == 200
    rec = r2.json()
    assert rec["status"] == "completed"
    assert rec["company"] == "NVIDIA"
    assert rec["proposal_md"] == "# done"
    assert "persist" in rec["stages_completed"]


def test_create_run_rejects_blank_company(client):
    r = client.post(
        "/runs",
        json={"company": "", "industry": "x"},
    )
    assert r.status_code == 422


def test_create_run_rejects_bad_lang(client):
    r = client.post(
        "/runs",
        json={"company": "X", "industry": "y", "lang": "fr"},
    )
    assert r.status_code == 422


def test_get_run_404_for_unknown(client):
    r = client.get("/runs/nope")
    assert r.status_code == 404


def test_list_runs_newest_first(client, monkeypatch):
    monkeypatch.setattr("src.api.runner.execute_run", _fake_execute_run_factory())

    for name in ("A", "B", "C"):
        r = client.post("/runs", json={"company": name, "industry": "x"})
        assert r.status_code == 202

    r = client.get("/runs")
    assert r.status_code == 200
    runs = r.json()["runs"]
    assert len(runs) == 3
    companies = [x["company"] for x in runs]
    # Newest first — companies created later should appear earlier in list
    assert companies == sorted(companies, reverse=True)


def test_failed_run_surfaces_status(client, monkeypatch):
    monkeypatch.setattr(
        "src.api.runner.execute_run",
        _fake_execute_run_factory(status="failed"),
    )
    r = client.post("/runs", json={"company": "Z", "industry": "x"})
    run_id = r.json()["run_id"]
    r2 = client.get(f"/runs/{run_id}")
    body = r2.json()
    assert body["status"] == "failed"
    assert body["failed_stage"] == "draft"
    assert body["proposal_md"] is None


def test_sse_stream_emits_events_and_terminates(client, monkeypatch):
    monkeypatch.setattr("src.api.runner.execute_run", _fake_execute_run_factory())

    r = client.post("/runs", json={"company": "NVIDIA", "industry": "x"})
    run_id = r.json()["run_id"]

    with client.stream("GET", f"/runs/{run_id}/events") as stream:
        body_chunks: list[str] = []
        for raw in stream.iter_lines():
            if raw:
                body_chunks.append(raw)
            if len(body_chunks) > 200:
                break
    text = "\n".join(body_chunks)
    assert "event: run_queued" in text or "event: run_started" in text
    assert "event: run_completed" in text
    assert "stage_completed" in text
