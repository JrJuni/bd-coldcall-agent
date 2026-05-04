"""Phase 10 P10-2b — /discovery endpoint tests.

Strategy mirrors `test_api_runs.py`:
- TestClient dispatches BackgroundTasks synchronously after the response
  so by the time `.post()` returns the run is in its final state.
- We monkeypatch `_runner.execute_discovery_run` (module-attr) so the
  real `discover_targets()` (Sonnet + RAG) never runs.
- Recompute uses `_runner.execute_discovery_recompute` directly — that
  function calls `_scoring.calc_final_score` / `decide_tier` which we
  let run for real (deterministic, fast, no LLM).

DO NOT rule: routes import `from src.api import runner as _runner` and
`from src.api import store as _store`, never `from src.api.runner
import execute_*` directly.
"""
from __future__ import annotations

import os

os.environ["API_SKIP_WARMUP"] = "1"

import pytest
from fastapi.testclient import TestClient

from src.api import store as _store
from src.api.config import reset_api_settings_cache


_BASE_BODY = {
    "namespace": "default",
    "regions": [],
    "product": "databricks",
    "lang": "en",
    "n_industries": 2,
    "n_per_industry": 2,
    "include_sector_leaders": False,
}


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


def _fake_run_factory(*, status: str = "completed"):
    """Return a stand-in execute_discovery_run that fills SQLite with
    deterministic candidates and marks the run completed/failed.

    Schema mirrors what the real `Candidate` model emits — every
    candidate has the 6 score dimensions (0-10 ints) plus tier/score.
    """

    def _fake(
        *,
        run_id: str,
        namespace: str,
        regions: list[str],
        product: str,
        seed_summary,
        seed_query,
        top_k,
        n_industries: int,
        n_per_industry: int,
        lang: str,
        include_sector_leaders: bool,
        store=None,
    ):
        s = store or _store.get_discovery_store()
        rec = s.get_run(run_id)
        assert rec is not None
        s.update_run(run_id, status="running", started_at="t0")
        s.append_event(run_id, "run_started", {})

        if status == "failed":
            s.update_run(
                run_id,
                status="failed",
                failed_stage="discover_targets",
                error_message="boom",
                ended_at="t1",
            )
            s.append_event(run_id, "run_failed", {"error_type": "RuntimeError"})
            return

        # Two industries × two candidates each
        cands: list[dict] = []
        for i, industry in enumerate(("Financial Services", "Retail")):
            for j in range(n_per_industry):
                cands.append(
                    {
                        "name": f"Co{i}{j}",
                        "industry": industry,
                        "scores": {
                            "pain_severity": 8 - j,
                            "data_complexity": 7,
                            "governance_need": 6,
                            "ai_maturity": 7,
                            "buying_trigger": 6,
                            "displacement_ease": 5,
                        },
                        "final_score": round(7.0 - j * 0.5, 2),
                        "tier": "S" if j == 0 else "A",
                        "rationale": f"rationale {i}{j}",
                        "status": "active",
                    }
                )
        s.insert_candidates(run_id, cands)
        s.update_run(
            run_id,
            seed_doc_count=1,
            seed_chunk_count=64,
            seed_summary=seed_summary or "fake",
            usage={"input_tokens": 100, "output_tokens": 50},
            status="completed",
            ended_at="t1",
        )
        s.append_event(
            run_id,
            "run_completed",
            {"candidate_count": len(cands)},
        )

    return _fake


# ── runs ───────────────────────────────────────────────────────────────


def test_create_discovery_run_persists_candidates(client, monkeypatch):
    monkeypatch.setattr(
        "src.api.runner.execute_discovery_run", _fake_run_factory()
    )
    r = client.post("/discovery/runs", json=_BASE_BODY)
    assert r.status_code == 202, r.text
    body = r.json()
    run_id = body["run_id"]
    assert run_id.startswith("discover-")

    r2 = client.get(f"/discovery/runs/{run_id}")
    assert r2.status_code == 200
    detail = r2.json()
    assert detail["status"] == "completed"
    assert detail["candidate_count"] == 4
    assert detail["seed_chunk_count"] == 64
    assert len(detail["candidates"]) == 4
    assert detail["tier_distribution"] == {"S": 2, "A": 2}
    # Newest-first ordering inside list_runs is exercised below
    assert detail["candidates"][0]["scores"]["pain_severity"] in (7, 8)


def test_failed_discovery_run_surfaces_error(client, monkeypatch):
    monkeypatch.setattr(
        "src.api.runner.execute_discovery_run",
        _fake_run_factory(status="failed"),
    )
    r = client.post("/discovery/runs", json=_BASE_BODY)
    run_id = r.json()["run_id"]
    r2 = client.get(f"/discovery/runs/{run_id}")
    body = r2.json()
    assert body["status"] == "failed"
    assert body["failed_stage"] == "discover_targets"
    assert body["error_message"] == "boom"


def test_create_discovery_run_validates_inputs(client):
    # Phase 12 — regions must be ISO alpha-2 (or "global"); 4-letter junk
    # like "moon" is rejected.
    bad = dict(_BASE_BODY, regions=["moon"])
    r = client.post("/discovery/runs", json=bad)
    assert r.status_code == 422, r.text
    bad2 = dict(_BASE_BODY, n_industries=0)
    r2 = client.post("/discovery/runs", json=bad2)
    assert r2.status_code == 422


def test_create_discovery_run_accepts_legacy_region_field(client, monkeypatch):
    """Pre-Phase-12 clients send `region: "any"` — the validator should
    fold it into `regions=[]` transparently so deployments don't break
    during a frontend rollout."""
    monkeypatch.setattr(
        "src.api.runner.execute_discovery_run", _fake_run_factory()
    )
    body = {k: v for k, v in _BASE_BODY.items() if k != "regions"}
    body["region"] = "any"
    r = client.post("/discovery/runs", json=body)
    assert r.status_code == 202, r.text
    detail = client.get(f"/discovery/runs/{r.json()['run_id']}").json()
    assert detail["regions"] == []


def test_create_discovery_run_accepts_multi_country_regions(client, monkeypatch):
    monkeypatch.setattr(
        "src.api.runner.execute_discovery_run", _fake_run_factory()
    )
    body = dict(_BASE_BODY, regions=["kr", "jp"])
    r = client.post("/discovery/runs", json=body)
    assert r.status_code == 202, r.text
    detail = client.get(f"/discovery/runs/{r.json()['run_id']}").json()
    assert detail["regions"] == ["kr", "jp"]


def test_list_discovery_runs_newest_first(client, monkeypatch):
    monkeypatch.setattr(
        "src.api.runner.execute_discovery_run", _fake_run_factory()
    )
    for _ in range(3):
        r = client.post("/discovery/runs", json=_BASE_BODY)
        assert r.status_code == 202

    r = client.get("/discovery/runs")
    assert r.status_code == 200
    runs = r.json()["runs"]
    assert len(runs) == 3
    # Newest first
    times = [run["created_at"] for run in runs]
    assert times == sorted(times, reverse=True)


def test_get_discovery_run_404_for_unknown(client):
    r = client.get("/discovery/runs/nope")
    assert r.status_code == 404


def test_delete_discovery_run_cascades_candidates(client, monkeypatch):
    monkeypatch.setattr(
        "src.api.runner.execute_discovery_run", _fake_run_factory()
    )
    r = client.post("/discovery/runs", json=_BASE_BODY)
    run_id = r.json()["run_id"]

    detail = client.get(f"/discovery/runs/{run_id}").json()
    assert detail["candidate_count"] == 4

    r2 = client.delete(f"/discovery/runs/{run_id}")
    assert r2.status_code == 204
    r3 = client.get(f"/discovery/runs/{run_id}")
    assert r3.status_code == 404
    # candidates table also cleared (DiscoveryStore.list_candidates returns [])
    s = _store.get_discovery_store()
    assert s.list_candidates(run_id) == []


# ── candidates ─────────────────────────────────────────────────────────


def test_patch_candidate_updates_scores_and_rationale(client, monkeypatch):
    monkeypatch.setattr(
        "src.api.runner.execute_discovery_run", _fake_run_factory()
    )
    run = client.post("/discovery/runs", json=_BASE_BODY).json()
    cand = client.get(f"/discovery/runs/{run['run_id']}").json()["candidates"][0]
    cid = cand["id"]

    new_scores = dict(cand["scores"])
    new_scores["pain_severity"] = 9
    r = client.patch(
        f"/discovery/candidates/{cid}",
        json={
            "scores": new_scores,
            "rationale": "edited",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scores"]["pain_severity"] == 9
    assert body["rationale"] == "edited"
    # tier left untouched
    assert body["tier"] == cand["tier"]


def test_delete_candidate(client, monkeypatch):
    monkeypatch.setattr(
        "src.api.runner.execute_discovery_run", _fake_run_factory()
    )
    run = client.post("/discovery/runs", json=_BASE_BODY).json()
    cands = client.get(f"/discovery/runs/{run['run_id']}").json()["candidates"]
    cid = cands[0]["id"]
    r = client.delete(f"/discovery/candidates/{cid}")
    assert r.status_code == 204
    detail = client.get(f"/discovery/runs/{run['run_id']}").json()
    assert detail["candidate_count"] == 3


def test_patch_candidate_404(client):
    r = client.patch("/discovery/candidates/9999", json={"rationale": "x"})
    assert r.status_code == 404


# ── recompute ──────────────────────────────────────────────────────────


def test_recompute_changes_tier_distribution(client, monkeypatch):
    """Equal weights across 6 dims with our fake scores → all candidates
    get the same final_score, which breaks the 2S/2A split apart from the
    fake values seeded by the runner. We just assert the endpoint returns
    a coherent tier_distribution and the candidates' final_score updates.
    """
    monkeypatch.setattr(
        "src.api.runner.execute_discovery_run", _fake_run_factory()
    )
    run = client.post("/discovery/runs", json=_BASE_BODY).json()
    run_id = run["run_id"]

    # Equal weights summing to 1.0 across the 6 known dimensions
    equal = {
        "pain_severity": 1 / 6,
        "data_complexity": 1 / 6,
        "governance_need": 1 / 6,
        "ai_maturity": 1 / 6,
        "buying_trigger": 1 / 6,
        "displacement_ease": 1 / 6,
    }
    r = client.post(
        f"/discovery/runs/{run_id}/recompute", json={"weights": equal}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["weights_applied"]["pain_severity"] == pytest.approx(1 / 6)
    assert sum(body["tier_distribution"].values()) == 4
    # final_score must now reflect equal-weight average of seeded scores
    for c in body["candidates"]:
        score = sum(c["scores"].values()) / 6
        assert c["final_score"] == pytest.approx(score, abs=0.01)


def test_recompute_404_for_unknown_run(client):
    r = client.post("/discovery/runs/nope/recompute", json={})
    assert r.status_code == 404


def test_recompute_normalizes_off_one_weights(client, monkeypatch):
    monkeypatch.setattr(
        "src.api.runner.execute_discovery_run", _fake_run_factory()
    )
    run = client.post("/discovery/runs", json=_BASE_BODY).json()
    # Sum = 6.0, runner should auto-normalize to ~0.166...
    weights = {d: 1.0 for d in (
        "pain_severity", "data_complexity", "governance_need",
        "ai_maturity", "buying_trigger", "displacement_ease",
    )}
    r = client.post(
        f"/discovery/runs/{run['run_id']}/recompute", json={"weights": weights}
    )
    assert r.status_code == 200
    applied = r.json()["weights_applied"]
    assert applied["pain_severity"] == pytest.approx(1 / 6)


# ── promote ────────────────────────────────────────────────────────────


def test_promote_candidate_creates_target(client, monkeypatch):
    monkeypatch.setattr(
        "src.api.runner.execute_discovery_run", _fake_run_factory()
    )
    run = client.post("/discovery/runs", json=_BASE_BODY).json()
    cand = client.get(f"/discovery/runs/{run['run_id']}").json()["candidates"][0]
    cid = cand["id"]
    r = client.post(f"/discovery/candidates/{cid}/promote")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["candidate_id"] == cid
    assert body["target_id"] >= 1
    assert body["candidate_status"] == "promoted"

    # Target row exists with created_from = "discovery_promote"
    targets = client.get("/targets").json()["targets"]
    assert len(targets) == 1
    t = targets[0]
    assert t["name"] == cand["name"]
    assert t["industry"] == cand["industry"]
    assert t["created_from"] == "discovery_promote"
    assert t["discovery_candidate_id"] == cid

    # Candidate row updated
    again = client.get(f"/discovery/runs/{run['run_id']}").json()
    target_cand = next(c for c in again["candidates"] if c["id"] == cid)
    assert target_cand["status"] == "promoted"


def test_promote_candidate_404(client):
    r = client.post("/discovery/candidates/9999/promote")
    assert r.status_code == 404
