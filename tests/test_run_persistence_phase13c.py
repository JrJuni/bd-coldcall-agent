"""Phase 13C M9 - RunStore terminal-snapshot persistence.

The hybrid choice (option c) writes a metadata row when a run transitions
to `completed` / `failed`. In-flight runs stay in the process-local
dict. These tests cover:

  1. A run that never reaches a terminal status writes NOTHING.
  2. The first transition to `completed` writes one row.
  3. A subsequent update (e.g. proposal_md set after completion) updates
     the same row, not a duplicate.
  4. `failed` runs are persisted with their error trail.
  5. `list_persisted` returns the rows newest-first.
"""
from __future__ import annotations

import sqlalchemy as sa

from src.api.models.run import Run
from src.api.orm import Base, make_engine, make_session_factory
from src.api.store import RunStore


def _build_store(tmp_path):
    db_path = tmp_path / "runs_m9.db"
    engine = make_engine(f"sqlite:///{db_path.as_posix()}")
    Base.metadata.create_all(engine)
    sf = make_session_factory(engine)
    return RunStore(session_factory=sf), sf


def test_inflight_runs_are_not_persisted(tmp_path):
    store, sf = _build_store(tmp_path)
    store.create(
        run_id="r1",
        company="Acme",
        industry="semiconductor",
        lang="en",
    )
    store.update("r1", status="running", current_stage="brave_search")
    with sf() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(Run)) == 0


def test_terminal_transition_writes_snapshot(tmp_path):
    store, sf = _build_store(tmp_path)
    store.create(
        run_id="r2",
        company="Acme",
        industry="semiconductor",
        lang="en",
        claude_model="claude-sonnet-4-6",
    )
    store.update("r2", status="running", started_at="2026-05-19T00:00:00+00:00")
    store.update(
        "r2",
        status="completed",
        ended_at="2026-05-19T00:01:30+00:00",
        duration_s=90.0,
        usage={"input_tokens": 1234, "output_tokens": 567},
        proposal_md="# Proposal\n\n...",
        proposal_points_count=4,
    )
    with sf() as s:
        rows = s.scalars(sa.select(Run)).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.run_id == "r2"
        assert row.status == "completed"
        assert row.duration_s == 90.0
        assert row.proposal_points_count == 4
        assert row.claude_model == "claude-sonnet-4-6"
        assert '"input_tokens": 1234' in (row.usage_json or "")


def test_post_terminal_update_overwrites_same_row(tmp_path):
    store, sf = _build_store(tmp_path)
    store.create(run_id="r3", company="X", industry="y", lang="en")
    store.update("r3", status="completed", proposal_md="v1")
    store.update("r3", status="completed", proposal_md="v2")
    with sf() as s:
        rows = s.scalars(sa.select(Run)).all()
        assert len(rows) == 1
        assert rows[0].proposal_md == "v2"


def test_failed_runs_are_persisted_with_errors(tmp_path):
    store, sf = _build_store(tmp_path)
    store.create(run_id="r4", company="X", industry="y", lang="en")
    store.update(
        "r4",
        status="failed",
        failed_stage="fetch",
        errors=[{"stage": "fetch", "message": "timeout"}],
        ended_at="2026-05-19T00:00:30+00:00",
    )
    with sf() as s:
        rows = s.scalars(sa.select(Run)).all()
        assert len(rows) == 1
        assert rows[0].status == "failed"
        assert rows[0].failed_stage == "fetch"
        assert "timeout" in (rows[0].errors_json or "")


def test_list_persisted_returns_newest_first(tmp_path):
    store, sf = _build_store(tmp_path)
    for i, ts in enumerate(
        ["2026-05-19T00:00:00+00:00", "2026-05-19T00:00:10+00:00"]
    ):
        store.create(run_id=f"r{i}", company="X", industry="y", lang="en")
        # Force created_at so ordering is deterministic.
        store._runs[f"r{i}"].created_at = ts
        store.update(f"r{i}", status="completed")
    rows = store.list_persisted()
    assert [r["run_id"] for r in rows] == ["r1", "r0"]
    assert rows[0]["_source"] == "persisted"


def test_list_persisted_returns_empty_when_no_factory():
    """Sanity: RunStore() without a session_factory acts in-memory-only."""
    store = RunStore(session_factory=None)
    store.create(run_id="r", company="X", industry="y", lang="en")
    store.update("r", status="completed")
    assert store.list_persisted() == []
