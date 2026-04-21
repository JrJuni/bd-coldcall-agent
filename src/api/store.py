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

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


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


_run_store: RunStore | None = None
_ingest_store: IngestStore | None = None


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


def reset_stores() -> None:
    """Test hook — drop cached singletons so each test starts empty."""
    global _run_store, _ingest_store
    _run_store = None
    _ingest_store = None
