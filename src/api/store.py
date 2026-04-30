"""Phase 7 — in-memory RunStore and ingest task registry.

Runs are appended to an event log (per-record) so SSE subscribers can
resume from any seq number without a queue. Event log writes are guarded
by a threading.Lock because `run_streaming` executes in a worker thread
(FastAPI `BackgroundTasks` dispatches sync callables through anyio's
thread pool) while SSE reads happen on the event loop.

State here is intentionally process-local — a true "run history" table
belongs to the post-MVP backlog (see `docs/status.md` 장기 과제).
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.api import db as _db


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class RunEvent:
    seq: int
    kind: str  # "status", "stage", "completed", "failed", "error"
    ts: str
    payload: dict[str, Any]


@dataclass
class RunRecord:
    run_id: str
    company: str
    industry: str
    lang: str
    status: str = "queued"  # queued | running | failed | completed
    current_stage: str | None = None
    stages_completed: list[str] = field(default_factory=list)
    failed_stage: str | None = None
    created_at: str = field(default_factory=_now_iso)
    started_at: str | None = None
    ended_at: str | None = None
    duration_s: float | None = None
    errors: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    article_counts: dict[str, int] = field(default_factory=dict)
    proposal_points_count: int = 0
    proposal_md: str | None = None
    output_dir: str | None = None
    events: list[RunEvent] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def append_event(self, kind: str, payload: dict[str, Any]) -> RunEvent:
        with self._lock:
            seq = len(self.events) + 1
            ev = RunEvent(seq=seq, kind=kind, ts=_now_iso(), payload=payload)
            self.events.append(ev)
            return ev

    def snapshot_events(self, since_seq: int = 0) -> list[RunEvent]:
        with self._lock:
            return [ev for ev in self.events if ev.seq > since_seq]


class RunStore:
    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}
        self._lock = threading.Lock()

    def create(
        self,
        *,
        run_id: str,
        company: str,
        industry: str,
        lang: str,
    ) -> RunRecord:
        with self._lock:
            record = RunRecord(
                run_id=run_id,
                company=company,
                industry=industry,
                lang=lang,
            )
            self._runs[run_id] = record
            return record

    def get(self, run_id: str) -> RunRecord | None:
        return self._runs.get(run_id)

    def list(self) -> list[RunRecord]:
        with self._lock:
            return list(self._runs.values())

    def update(self, run_id: str, **fields: Any) -> RunRecord | None:
        record = self._runs.get(run_id)
        if record is None:
            return None
        with record._lock:
            for k, v in fields.items():
                setattr(record, k, v)
        return record


@dataclass
class IngestTask:
    task_id: str
    status: str = "queued"  # queued | running | completed | failed
    created_at: str = field(default_factory=_now_iso)
    ended_at: str | None = None
    message: str | None = None
    params: dict[str, Any] = field(default_factory=dict)


class IngestStore:
    def __init__(self) -> None:
        self._tasks: dict[str, IngestTask] = {}
        self._lock = threading.Lock()

    def create(self, *, task_id: str, params: dict[str, Any]) -> IngestTask:
        with self._lock:
            task = IngestTask(task_id=task_id, params=dict(params))
            self._tasks[task_id] = task
            return task

    def get(self, task_id: str) -> IngestTask | None:
        return self._tasks.get(task_id)

    def update(self, task_id: str, **fields: Any) -> IngestTask | None:
        task = self._tasks.get(task_id)
        if task is None:
            return None
        for k, v in fields.items():
            setattr(task, k, v)
        return task


class TargetStore:
    """SQLite-backed CRUD over the `targets` table.

    Stateless except for the DB path — every method opens its own
    short-lived connection via `db.connect()` so the store is safe to
    share across worker threads (FastAPI BackgroundTasks pool) without
    extra locking.
    """

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = Path(db_path)

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        aliases_raw = row["aliases_json"]
        try:
            aliases = json.loads(aliases_raw) if aliases_raw else []
        except json.JSONDecodeError:
            aliases = []
        return {
            "id": row["id"],
            "name": row["name"],
            "industry": row["industry"],
            "aliases": aliases,
            "notes": row["notes"],
            "stage": row["stage"],
            "created_from": row["created_from"],
            "discovery_candidate_id": row["discovery_candidate_id"],
            "last_run_id": row["last_run_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list(self) -> list[dict[str, Any]]:
        with _db.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM targets ORDER BY id DESC"
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def create(
        self,
        *,
        name: str,
        industry: str,
        aliases: list[str] | None = None,
        notes: str | None = None,
        stage: str = "planned",
        created_from: str = "manual",
        discovery_candidate_id: int | None = None,
        last_run_id: str | None = None,
    ) -> dict[str, Any]:
        ts = _now_iso()
        aliases_json = json.dumps(aliases or [], ensure_ascii=False)
        with _db.connect(self._db_path) as conn:
            cur = conn.execute(
                "INSERT INTO targets("
                " name, industry, aliases_json, notes, stage, created_from,"
                " discovery_candidate_id, last_run_id, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    name, industry, aliases_json, notes, stage, created_from,
                    discovery_candidate_id, last_run_id, ts, ts,
                ),
            )
            new_id = cur.lastrowid
            row = conn.execute(
                "SELECT * FROM targets WHERE id=?", (new_id,)
            ).fetchone()
        return self._row_to_dict(row)

    def get(self, target_id: int) -> dict[str, Any] | None:
        with _db.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM targets WHERE id=?", (target_id,)
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def update(self, target_id: int, **fields: Any) -> dict[str, Any] | None:
        # Only known columns are accepted; aliases is a list → JSON.
        col_map: dict[str, Any] = {}
        for key in ("name", "industry", "notes", "stage", "last_run_id"):
            if key in fields and fields[key] is not None:
                col_map[key] = fields[key]
        if "aliases" in fields and fields["aliases"] is not None:
            col_map["aliases_json"] = json.dumps(
                fields["aliases"], ensure_ascii=False
            )
        if not col_map:
            return self.get(target_id)
        col_map["updated_at"] = _now_iso()
        sets = ", ".join(f"{k}=?" for k in col_map.keys())
        params = list(col_map.values()) + [target_id]
        with _db.connect(self._db_path) as conn:
            cur = conn.execute(
                f"UPDATE targets SET {sets} WHERE id=?", params
            )
            if cur.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT * FROM targets WHERE id=?", (target_id,)
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def delete(self, target_id: int) -> bool:
        with _db.connect(self._db_path) as conn:
            cur = conn.execute(
                "DELETE FROM targets WHERE id=?", (target_id,)
            )
            return cur.rowcount > 0


class DiscoveryStore:
    """SQLite-backed discovery_runs + discovery_candidates CRUD.

    Mirrors `TargetStore` for persistence (every method opens its own
    short-lived connection) but adds an in-memory event log keyed by
    run_id, like `RunStore`. The event log is what SSE consumers poll;
    the SQLite tables hold authoritative state for any new HTTP request.
    """

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = Path(db_path)
        self._events: dict[str, list[RunEvent]] = {}
        self._event_lock = threading.Lock()

    # ── Events (in-memory, like RunStore) ─────────────────────────────

    def append_event(
        self, run_id: str, kind: str, payload: dict[str, Any]
    ) -> RunEvent:
        with self._event_lock:
            log = self._events.setdefault(run_id, [])
            seq = len(log) + 1
            ev = RunEvent(seq=seq, kind=kind, ts=_now_iso(), payload=payload)
            log.append(ev)
            return ev

    def snapshot_events(self, run_id: str, since_seq: int = 0) -> list[RunEvent]:
        with self._event_lock:
            log = self._events.get(run_id, [])
            return [ev for ev in log if ev.seq > since_seq]

    # ── Runs ──────────────────────────────────────────────────────────

    @staticmethod
    def _run_row_to_dict(row: Any) -> dict[str, Any]:
        usage_raw = row["usage_json"] if "usage_json" in row.keys() else None
        try:
            usage = json.loads(usage_raw) if usage_raw else {}
        except json.JSONDecodeError:
            usage = {}
        return {
            "run_id": row["run_id"],
            "generated_at": row["generated_at"],
            "seed_doc_count": row["seed_doc_count"] or 0,
            "seed_chunk_count": row["seed_chunk_count"] or 0,
            "seed_summary": row["seed_summary"],
            "product": row["product"] or "",
            "region": row["region"] or "any",
            "lang": row["lang"] or "en",
            "namespace": row["namespace"] or "default",
            "status": row["status"] or "queued",
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
            "failed_stage": row["failed_stage"],
            "error_message": row["error_message"],
            "source_yaml_path": row["source_yaml_path"],
            "usage": usage,
            "created_at": row["created_at"],
        }

    def list_runs(self) -> list[dict[str, Any]]:
        with _db.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM discovery_runs ORDER BY created_at DESC"
            ).fetchall()
            results: list[dict[str, Any]] = []
            for r in rows:
                d = self._run_row_to_dict(r)
                cand_rows = conn.execute(
                    "SELECT tier, COUNT(*) as n FROM discovery_candidates "
                    "WHERE run_id=? GROUP BY tier",
                    (d["run_id"],),
                ).fetchall()
                d["candidate_count"] = sum(int(cr["n"]) for cr in cand_rows)
                d["tier_distribution"] = {
                    cr["tier"]: int(cr["n"]) for cr in cand_rows
                }
                results.append(d)
        return results

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with _db.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM discovery_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        return self._run_row_to_dict(row) if row else None

    def create_run(
        self,
        *,
        run_id: str,
        generated_at: str,
        namespace: str,
        product: str,
        region: str,
        lang: str,
        seed_summary: str | None,
    ) -> dict[str, Any]:
        ts = _now_iso()
        with _db.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO discovery_runs("
                " run_id, generated_at, namespace, product, region, lang,"
                " seed_summary, status, usage_json, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id, generated_at, namespace, product, region, lang,
                    seed_summary, "queued", "{}", ts,
                ),
            )
            row = conn.execute(
                "SELECT * FROM discovery_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        return self._run_row_to_dict(row)

    def update_run(self, run_id: str, **fields: Any) -> dict[str, Any] | None:
        col_map: dict[str, Any] = {}
        for key in (
            "status", "started_at", "ended_at", "failed_stage",
            "error_message", "seed_doc_count", "seed_chunk_count",
            "seed_summary", "generated_at",
        ):
            if key in fields and fields[key] is not None:
                col_map[key] = fields[key]
        if "usage" in fields and fields["usage"] is not None:
            col_map["usage_json"] = json.dumps(
                fields["usage"], ensure_ascii=False
            )
        if not col_map:
            return self.get_run(run_id)
        sets = ", ".join(f"{k}=?" for k in col_map.keys())
        params = list(col_map.values()) + [run_id]
        with _db.connect(self._db_path) as conn:
            cur = conn.execute(
                f"UPDATE discovery_runs SET {sets} WHERE run_id=?", params
            )
            if cur.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT * FROM discovery_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        return self._run_row_to_dict(row) if row else None

    def delete_run(self, run_id: str) -> bool:
        with _db.connect(self._db_path) as conn:
            cur = conn.execute(
                "DELETE FROM discovery_runs WHERE run_id=?", (run_id,)
            )
            return cur.rowcount > 0

    # ── Candidates ────────────────────────────────────────────────────

    @staticmethod
    def _cand_row_to_dict(row: Any) -> dict[str, Any]:
        try:
            scores = json.loads(row["scores_json"]) if row["scores_json"] else {}
        except json.JSONDecodeError:
            scores = {}
        return {
            "id": row["id"],
            "run_id": row["run_id"],
            "name": row["name"],
            "industry": row["industry"],
            "scores": scores,
            "final_score": float(row["final_score"] or 0.0),
            "tier": row["tier"] or "C",
            "rationale": row["rationale"],
            "status": row["status"] or "active",
            "updated_at": row["updated_at"],
        }

    def list_candidates(self, run_id: str) -> list[dict[str, Any]]:
        with _db.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM discovery_candidates"
                " WHERE run_id=? ORDER BY final_score DESC, id ASC",
                (run_id,),
            ).fetchall()
        return [self._cand_row_to_dict(r) for r in rows]

    def get_candidate(self, candidate_id: int) -> dict[str, Any] | None:
        with _db.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM discovery_candidates WHERE id=?", (candidate_id,)
            ).fetchone()
        return self._cand_row_to_dict(row) if row else None

    def insert_candidates(
        self, run_id: str, candidates: list[dict[str, Any]]
    ) -> None:
        if not candidates:
            return
        ts = _now_iso()
        rows = []
        for c in candidates:
            rows.append(
                (
                    run_id,
                    c["name"],
                    c["industry"],
                    json.dumps(c.get("scores", {}), ensure_ascii=False),
                    float(c.get("final_score", 0.0)),
                    c.get("tier", "C"),
                    c.get("rationale"),
                    c.get("status", "active"),
                    ts,
                )
            )
        with _db.connect(self._db_path) as conn:
            conn.executemany(
                "INSERT INTO discovery_candidates("
                " run_id, name, industry, scores_json, final_score, tier,"
                " rationale, status, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                rows,
            )

    def update_candidate(
        self, candidate_id: int, **fields: Any
    ) -> dict[str, Any] | None:
        col_map: dict[str, Any] = {}
        for key in ("name", "industry", "rationale", "status", "tier"):
            if key in fields and fields[key] is not None:
                col_map[key] = fields[key]
        if "scores" in fields and fields["scores"] is not None:
            col_map["scores_json"] = json.dumps(
                fields["scores"], ensure_ascii=False
            )
        if "final_score" in fields and fields["final_score"] is not None:
            col_map["final_score"] = float(fields["final_score"])
        if not col_map:
            return self.get_candidate(candidate_id)
        col_map["updated_at"] = _now_iso()
        sets = ", ".join(f"{k}=?" for k in col_map.keys())
        params = list(col_map.values()) + [candidate_id]
        with _db.connect(self._db_path) as conn:
            cur = conn.execute(
                f"UPDATE discovery_candidates SET {sets} WHERE id=?", params
            )
            if cur.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT * FROM discovery_candidates WHERE id=?", (candidate_id,)
            ).fetchone()
        return self._cand_row_to_dict(row) if row else None

    def delete_candidate(self, candidate_id: int) -> bool:
        with _db.connect(self._db_path) as conn:
            cur = conn.execute(
                "DELETE FROM discovery_candidates WHERE id=?", (candidate_id,)
            )
            return cur.rowcount > 0

    def bulk_update_tiers(
        self,
        updates: list[tuple[int, float, str]],  # (id, final_score, tier)
    ) -> None:
        if not updates:
            return
        ts = _now_iso()
        rows = [(score, tier, ts, cid) for cid, score, tier in updates]
        with _db.connect(self._db_path) as conn:
            conn.executemany(
                "UPDATE discovery_candidates"
                " SET final_score=?, tier=?, updated_at=? WHERE id=?",
                rows,
            )


_run_store: RunStore | None = None
_ingest_store: IngestStore | None = None
_target_store: TargetStore | None = None
_discovery_store: DiscoveryStore | None = None


def get_run_store() -> RunStore:
    global _run_store
    if _run_store is None:
        _run_store = RunStore()
    return _run_store


def get_ingest_store() -> IngestStore:
    global _ingest_store
    if _ingest_store is None:
        _ingest_store = IngestStore()
    return _ingest_store


def get_target_store() -> TargetStore:
    """Return a TargetStore bound to the configured app DB path.

    Resolved lazily so tests that override `API_APP_DB` (and call
    `reset_api_settings_cache`) get a fresh store after `reset_stores()`.
    """
    global _target_store
    if _target_store is None:
        from src.api.config import get_api_settings

        _target_store = TargetStore(get_api_settings().app_db)
    return _target_store


def get_discovery_store() -> DiscoveryStore:
    """Return a DiscoveryStore bound to the configured app DB path."""
    global _discovery_store
    if _discovery_store is None:
        from src.api.config import get_api_settings

        _discovery_store = DiscoveryStore(get_api_settings().app_db)
    return _discovery_store


def reset_stores() -> None:
    """Test hook — drop cached singletons so each test starts empty."""
    global _run_store, _ingest_store, _target_store, _discovery_store
    _run_store = None
    _ingest_store = None
    _target_store = None
    _discovery_store = None
