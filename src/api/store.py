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
import re
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.api import db as _db


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# Phase 12 — discovery_runs.region storage compat shim.
# The column historically held a single enum value ("any"/"ko"/"us"/"eu"/"global");
# the API now exposes a list of ISO 3166-1 alpha-2 codes. We round-trip via a
# comma-joined string so the existing TEXT column needs no schema change, and
# legacy single-value rows still decode into the new list form.
_LEGACY_REGION_DECODE: dict[str, list[str]] = {
    "any": [],
    "global": ["global"],
    "ko": ["kr"],
    "us": ["us"],
    "eu": ["gb"],
}


def _decode_regions_column(raw: str | None) -> list[str]:
    if not raw:
        return []
    s = raw.strip()
    if not s:
        return []
    if "," in s:
        return [p.strip().lower() for p in s.split(",") if p.strip()]
    legacy = _LEGACY_REGION_DECODE.get(s.lower())
    if legacy is not None:
        return list(legacy)
    return [s.lower()]


def _encode_regions_column(regions: list[str]) -> str:
    if not regions:
        return "any"  # canonical empty marker; survives older clients reading directly
    return ",".join(r.strip().lower() for r in regions if r.strip())


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
    # The Claude model active at run-start. Stored once so that future
    # active-model swaps don't retroactively re-cost historical runs.
    claude_model: str | None = None
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
        claude_model: str | None = None,
    ) -> RunRecord:
        with self._lock:
            record = RunRecord(
                run_id=run_id,
                company=company,
                industry=industry,
                lang=lang,
                claude_model=claude_model,
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
        keys = row.keys()
        # Phase 12 — `region` column now stores a comma-joined list of ISO
        # alpha-2 codes (or "global"). Pre-Phase-12 rows hold a single
        # legacy enum ("any"/"ko"/"us"/"eu"/"global") which we map back to
        # a list at read time so the wire format stays consistent.
        regions = _decode_regions_column(row["region"])
        return {
            "run_id": row["run_id"],
            "generated_at": row["generated_at"],
            "seed_doc_count": row["seed_doc_count"] or 0,
            "seed_chunk_count": row["seed_chunk_count"] or 0,
            "seed_summary": row["seed_summary"],
            "product": row["product"] or "",
            "regions": regions,
            "lang": row["lang"] or "en",
            "namespace": row["namespace"] or "default",
            "status": row["status"] or "queued",
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
            "failed_stage": row["failed_stage"],
            "error_message": row["error_message"],
            "source_yaml_path": row["source_yaml_path"],
            "claude_model": row["claude_model"] if "claude_model" in keys else None,
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
        regions: list[str],
        lang: str,
        seed_summary: str | None,
        claude_model: str | None = None,
    ) -> dict[str, Any]:
        ts = _now_iso()
        region_blob = _encode_regions_column(regions)
        with _db.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO discovery_runs("
                " run_id, generated_at, namespace, product, region, lang,"
                " seed_summary, status, usage_json, claude_model, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id, generated_at, namespace, product, region_blob, lang,
                    seed_summary, "queued", "{}", claude_model, ts,
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


class InteractionStore:
    """SQLite-backed CRUD + LIKE search over the `interactions` table.

    Captured BD touchpoints (call/meeting/email/note) live here. The
    schema lets `target_id` be NULL so a free-text "I called Acme today"
    note works even before the company is registered as a Target. The
    LIKE search scans `company_name`, `raw_text`, and `contact_role` so
    "find every interaction that mentions Stripe" works without joins.
    """

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = Path(db_path)

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "target_id": row["target_id"],
            "company_name": row["company_name"],
            "kind": row["kind"],
            "occurred_at": row["occurred_at"],
            "outcome": row["outcome"],
            "raw_text": row["raw_text"],
            "contact_role": row["contact_role"],
            "created_at": row["created_at"],
        }

    def create(
        self,
        *,
        company_name: str,
        kind: str,
        occurred_at: str,
        target_id: int | None = None,
        outcome: str | None = None,
        raw_text: str | None = None,
        contact_role: str | None = None,
    ) -> dict[str, Any]:
        ts = _now_iso()
        with _db.connect(self._db_path) as conn:
            cur = conn.execute(
                "INSERT INTO interactions("
                " target_id, company_name, kind, occurred_at, outcome,"
                " raw_text, contact_role, created_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (
                    target_id,
                    company_name,
                    kind,
                    occurred_at,
                    outcome,
                    raw_text,
                    contact_role,
                    ts,
                ),
            )
            new_id = cur.lastrowid
            row = conn.execute(
                "SELECT * FROM interactions WHERE id=?", (new_id,)
            ).fetchone()
        return self._row_to_dict(row)

    def get(self, interaction_id: int) -> dict[str, Any] | None:
        with _db.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM interactions WHERE id=?", (interaction_id,)
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def list(
        self,
        *,
        company: str | None = None,
        target_id: int | None = None,
        q: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if company:
            clauses.append("company_name = ?")
            params.append(company)
        if target_id is not None:
            clauses.append("target_id = ?")
            params.append(target_id)
        if q:
            like = f"%{q}%"
            clauses.append(
                "(company_name LIKE ? OR raw_text LIKE ? OR contact_role LIKE ?)"
            )
            params.extend([like, like, like])
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            "SELECT * FROM interactions"
            f"{where} ORDER BY occurred_at DESC, id DESC LIMIT ?"
        )
        params.append(limit)
        with _db.connect(self._db_path) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def update(
        self, interaction_id: int, **fields: Any
    ) -> dict[str, Any] | None:
        col_map: dict[str, Any] = {}
        for key in (
            "company_name",
            "kind",
            "occurred_at",
            "outcome",
            "raw_text",
            "contact_role",
            "target_id",
        ):
            if key in fields:
                col_map[key] = fields[key]
        if not col_map:
            return self.get(interaction_id)
        sets = ", ".join(f"{k}=?" for k in col_map.keys())
        params = list(col_map.values()) + [interaction_id]
        with _db.connect(self._db_path) as conn:
            cur = conn.execute(
                f"UPDATE interactions SET {sets} WHERE id=?", params
            )
            if cur.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT * FROM interactions WHERE id=?", (interaction_id,)
            ).fetchone()
        return self._row_to_dict(row)

    def delete(self, interaction_id: int) -> bool:
        with _db.connect(self._db_path) as conn:
            cur = conn.execute(
                "DELETE FROM interactions WHERE id=?", (interaction_id,)
            )
        return cur.rowcount > 0


class NewsStore:
    """SQLite-backed CRUD over the `news_runs` table.

    One row per refresh task: queued/running/completed/failed status with
    cached `articles_json` blob (raw Brave hits + per-article meta). The
    UI reads `latest_for_namespace()` for the cache hit on /news/today,
    and `get(task_id)` for the polling hook after POST /news/refresh.
    """

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = Path(db_path)

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        try:
            articles = json.loads(row["articles_json"] or "[]")
        except (TypeError, json.JSONDecodeError):
            articles = []
        try:
            usage = json.loads(row["usage_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            usage = {}
        return {
            "task_id": row["task_id"],
            "namespace": row["namespace"],
            "generated_at": row["generated_at"],
            "seed_summary": row["seed_summary"],
            "seed_query": row["seed_query"],
            "lang": row["lang"],
            "days": row["days"],
            "status": row["status"],
            "article_count": row["article_count"],
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
            "error_message": row["error_message"],
            "sonnet_summary": row["sonnet_summary"],
            "ttl_hours": row["ttl_hours"],
            "articles": articles,
            "usage": usage,
            "created_at": row["created_at"] if "created_at" in row.keys() else None,
        }

    def create(
        self,
        *,
        task_id: str,
        namespace: str,
        seed_query: str | None,
        seed_summary: str | None,
        lang: str,
        days: int,
        ttl_hours: int = 12,
    ) -> dict[str, Any]:
        ts = _now_iso()
        with _db.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO news_runs("
                " task_id, namespace, generated_at, seed_summary, seed_query,"
                " articles_json, lang, days, status, article_count,"
                " ttl_hours, started_at, ended_at, error_message, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    task_id,
                    namespace,
                    ts,
                    seed_summary,
                    seed_query,
                    "[]",
                    lang,
                    days,
                    "queued",
                    0,
                    ttl_hours,
                    None,
                    None,
                    None,
                    ts,
                ),
            )
        return self.get(task_id)  # type: ignore[return-value]

    def update(self, task_id: str, **fields: Any) -> dict[str, Any] | None:
        if not fields:
            return self.get(task_id)
        col_map = dict(fields)
        if "articles" in col_map:
            col_map["articles_json"] = json.dumps(
                col_map.pop("articles") or [], ensure_ascii=False
            )
        if "usage" in col_map:
            col_map["usage_json"] = json.dumps(
                col_map.pop("usage") or {}, ensure_ascii=False
            )
        cols = list(col_map.keys())
        set_clause = ", ".join(f"{c}=?" for c in cols)
        values = [col_map[c] for c in cols] + [task_id]
        with _db.connect(self._db_path) as conn:
            cur = conn.execute(
                f"UPDATE news_runs SET {set_clause} WHERE task_id=?",
                values,
            )
            if cur.rowcount == 0:
                return None
        return self.get(task_id)

    def get(self, task_id: str) -> dict[str, Any] | None:
        with _db.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM news_runs WHERE task_id=?", (task_id,)
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def latest_for_namespace(
        self, namespace: str, *, status: str | None = "completed"
    ) -> dict[str, Any] | None:
        sql = "SELECT * FROM news_runs WHERE namespace=?"
        params: list[Any] = [namespace]
        if status:
            sql += " AND status=?"
            params.append(status)
        sql += " ORDER BY generated_at DESC LIMIT 1"
        with _db.connect(self._db_path) as conn:
            row = conn.execute(sql, params).fetchone()
        return self._row_to_dict(row) if row else None

    def list(
        self, *, namespace: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM news_runs"
        params: list[Any] = []
        if namespace:
            sql += " WHERE namespace=?"
            params.append(namespace)
        sql += " ORDER BY generated_at DESC LIMIT ?"
        params.append(limit)
        with _db.connect(self._db_path) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_dict(r) for r in rows]


class WorkspaceStore:
    """Phase 11 P11-0 — SQLite-backed CRUD over the `workspaces` table.

    The built-in `default` workspace is seeded by `init_db` and protected
    from deletion. External workspaces let users register arbitrary local
    paths (e.g. D:\\my-docs\\) as additional roots in the RAG tree.

    Slug is auto-generated from label; collisions get -2/-3 suffixes.
    abs_path is validated (absolute + exists + is_dir + not inside the
    project's data/ directory). abs_path is immutable post-create — only
    label can be patched.
    """

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = Path(db_path)

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "slug": row["slug"],
            "label": row["label"],
            "abs_path": row["abs_path"],
            "is_builtin": bool(row["is_builtin"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _slugify(label: str) -> str:
        s = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
        return s or "workspace"

    @staticmethod
    def _validate_abs_path(abs_path: str) -> Path:
        """Return resolved Path on success; raise ValueError otherwise.

        Rules: absolute + exists + is_dir + NOT inside <PROJECT_ROOT>/data
        (registering anywhere under data/ would collide with the built-in
        default workspace and the vectorstore).
        """
        if not abs_path or not abs_path.strip():
            raise ValueError("abs_path must not be empty")
        p = Path(abs_path)
        if not p.is_absolute():
            raise ValueError(f"abs_path must be absolute: {abs_path}")
        try:
            resolved = p.resolve(strict=False)
        except OSError as e:
            raise ValueError(f"abs_path could not be resolved: {e}")
        if not resolved.exists():
            raise ValueError(f"abs_path does not exist: {abs_path}")
        if not resolved.is_dir():
            raise ValueError(f"abs_path must be a directory: {abs_path}")
        from src.config.loader import PROJECT_ROOT

        data_root = (PROJECT_ROOT / "data").resolve()
        try:
            resolved.relative_to(data_root)
            inside_data = True
        except ValueError:
            inside_data = False
        if inside_data:
            raise ValueError(
                f"abs_path must not be inside the project's data/ directory: "
                f"{abs_path}"
            )
        return resolved

    def _next_slug(self, conn: sqlite3.Connection, label: str) -> str:
        base = self._slugify(label)
        candidate = base
        n = 2
        # default-ws namespaces live at data/vectorstore/<ns>/. An external
        # workspace would claim data/vectorstore/<slug>/ as its own root,
        # so a slug equal to an existing default-ws ns name would overlap
        # that directory on disk. Treat ns names as reserved alongside DB
        # slugs and auto-suffix on collision (same UX as slug-vs-slug).
        reserved_ns = self._default_ws_namespace_names()
        while True:
            row = conn.execute(
                "SELECT id FROM workspaces WHERE slug=?", (candidate,)
            ).fetchone()
            if row is None and candidate not in reserved_ns:
                return candidate
            candidate = f"{base}-{n}"
            n += 1

    @staticmethod
    def _default_ws_namespace_names() -> set[str]:
        """Names of namespaces under the default workspace's vectorstore root.

        Lazy + module-attr imports so test monkeypatches on
        `src.config.loader.get_settings` (and friends) flow through
        unchanged — DO NOT rule. Best-effort: any error returns an empty
        set so a broken filesystem state doesn't block workspace creation.
        """
        try:
            from src.config import loader as _loader
            from src.rag import namespace as _ns

            vs_path = Path(_loader.get_settings().rag.vectorstore_path)
            if not vs_path.is_absolute():
                vs_path = _loader.PROJECT_ROOT / vs_path
            return set(_ns.list_namespaces(vs_path))
        except Exception:
            return set()

    def list(self) -> list[dict[str, Any]]:
        with _db.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM workspaces"
                " ORDER BY is_builtin DESC, id ASC"
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def create(self, *, label: str, abs_path: str) -> dict[str, Any]:
        resolved = self._validate_abs_path(abs_path)
        ts = _now_iso()
        with _db.connect(self._db_path) as conn:
            slug = self._next_slug(conn, label)
            try:
                cur = conn.execute(
                    "INSERT INTO workspaces"
                    " (slug, label, abs_path, is_builtin, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?)",
                    (slug, label, str(resolved), 0, ts, ts),
                )
            except sqlite3.IntegrityError as e:
                # abs_path UNIQUE collision — another workspace already
                # registered this exact directory.
                raise ValueError(
                    f"abs_path is already registered as a workspace: {abs_path}"
                ) from e
            new_id = cur.lastrowid
            row = conn.execute(
                "SELECT * FROM workspaces WHERE id=?", (new_id,)
            ).fetchone()
        return self._row_to_dict(row)

    def get(self, workspace_id: int) -> dict[str, Any] | None:
        with _db.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM workspaces WHERE id=?", (workspace_id,)
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def get_by_slug(self, slug: str) -> dict[str, Any] | None:
        with _db.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM workspaces WHERE slug=?", (slug,)
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def update(
        self, workspace_id: int, *, label: str | None = None
    ) -> dict[str, Any] | None:
        # Only label is mutable. abs_path is intentionally immutable —
        # changing it would orphan the workspace's vectorstore directory
        # and confuse existing manifests.
        if label is None:
            return self.get(workspace_id)
        ts = _now_iso()
        with _db.connect(self._db_path) as conn:
            cur = conn.execute(
                "UPDATE workspaces SET label=?, updated_at=? WHERE id=?",
                (label, ts, workspace_id),
            )
            if cur.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT * FROM workspaces WHERE id=?", (workspace_id,)
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def delete(self, workspace_id: int, *, wipe_index: bool = False) -> bool:
        """Remove the workspace registration.

        The user-registered abs_path (source files) is NEVER touched —
        this method only mutates the project's own state.

        When `wipe_index=True`, the workspace's vectorstore directory
        (`data/vectorstore/<slug>/`) is also recursively removed and any
        cached AI summaries scoped to this slug are dropped. When False,
        those artifacts stay on disk so re-adding the same path with
        the same label restores the index for free.
        """
        import shutil

        with _db.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT slug, is_builtin FROM workspaces WHERE id=?",
                (workspace_id,),
            ).fetchone()
            if row is None:
                return False
            if row["is_builtin"]:
                raise ValueError(
                    "the built-in `default` workspace cannot be deleted"
                )
            slug = row["slug"]
            if wipe_index:
                conn.execute(
                    "DELETE FROM rag_summaries WHERE ws_slug=?", (slug,)
                )
            cur = conn.execute(
                "DELETE FROM workspaces WHERE id=?", (workspace_id,)
            )
            removed = cur.rowcount > 0
        # Wipe the vectorstore on-disk AFTER the DB commit so a tree-walk
        # failure never leaves the registry pointing at a half-removed dir.
        if removed and wipe_index:
            from src.rag.workspaces import _resolve_vectorstore_root

            try:
                vs_dir = _resolve_vectorstore_root() / slug
                if vs_dir.exists():
                    shutil.rmtree(vs_dir, ignore_errors=True)
            except Exception:
                # Best-effort — the DB row is already gone, so the UI
                # will show the workspace as removed regardless.
                pass
        return removed


_run_store: RunStore | None = None
_ingest_store: IngestStore | None = None
_target_store: TargetStore | None = None
_discovery_store: DiscoveryStore | None = None
_news_store: NewsStore | None = None
_interaction_store: InteractionStore | None = None
_workspace_store: WorkspaceStore | None = None


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


def get_news_store() -> NewsStore:
    """Return a NewsStore bound to the configured app DB path."""
    global _news_store
    if _news_store is None:
        from src.api.config import get_api_settings

        _news_store = NewsStore(get_api_settings().app_db)
    return _news_store


def get_interaction_store() -> InteractionStore:
    """Return an InteractionStore bound to the configured app DB path."""
    global _interaction_store
    if _interaction_store is None:
        from src.api.config import get_api_settings

        _interaction_store = InteractionStore(get_api_settings().app_db)
    return _interaction_store


def get_workspace_store() -> WorkspaceStore:
    """Return a WorkspaceStore bound to the configured app DB path."""
    global _workspace_store
    if _workspace_store is None:
        from src.api.config import get_api_settings

        _workspace_store = WorkspaceStore(get_api_settings().app_db)
    return _workspace_store


def reset_stores() -> None:
    """Test hook — drop cached singletons so each test starts empty."""
    global _run_store, _ingest_store, _target_store, _discovery_store
    global _news_store, _interaction_store, _workspace_store
    _run_store = None
    _ingest_store = None
    _target_store = None
    _discovery_store = None
    _news_store = None
    _interaction_store = None
    _workspace_store = None
