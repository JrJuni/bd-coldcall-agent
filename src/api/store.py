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
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from src.api import orm as _orm


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


_TERMINAL_STATUSES = frozenset({"completed", "failed"})


class RunStore:
    """In-flight run dict + (Phase 13C M9) terminal-snapshot persistence.

    Why hybrid:
      Option (a) "full persistence to DB" would have meant a new table
      backing the entire event log + per-record locks — a lot of new
      surface for a feature (run resume after restart) that Phase 13's
      agent-first narrative doesn't actually need. Option (b) "scope
      reduction" would have made the /runs history page empty after
      every restart, which felt regressive after the 13B dual-engine
      ORM investment. (c) writes the snapshot fields to the new `runs`
      table when a run reaches a terminal status. The in-memory dict
      still owns in-flight state + event logs; persistence only fires
      once a run has settled, so concurrent SSE consumers never see a
      half-written row.

    The session_factory is optional — when None, RunStore behaves
    exactly like the pre-Phase-13C in-memory-only version. Tests
    construct it without a factory and skip the persistence path.
    """

    def __init__(self, session_factory: Any | None = None) -> None:
        self._runs: dict[str, RunRecord] = {}
        self._lock = threading.Lock()
        self._sf = session_factory

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
        # Persist on terminal transition. Failures here don't bubble —
        # the in-memory record is authoritative; the DB row is purely
        # for the run-history page surviving a restart.
        if (
            self._sf is not None
            and record.status in _TERMINAL_STATUSES
        ):
            try:
                self._persist_snapshot(record)
            except Exception:  # noqa: BLE001
                import logging

                logging.getLogger(__name__).exception(
                    "RunStore: terminal snapshot write failed (run=%s)",
                    record.run_id,
                )
        return record

    def _persist_snapshot(self, record: RunRecord) -> None:
        """Upsert the terminal snapshot row for `record`.

        Uses DELETE-then-INSERT (rather than `INSERT OR REPLACE` /
        merge) so the helper stays dialect-agnostic across SQLite and
        Postgres.
        """
        from src.api.models.run import Run

        with self._sf() as session:
            session.execute(
                sa.delete(Run).where(Run.run_id == record.run_id)
            )
            session.add(
                Run(
                    run_id=record.run_id,
                    company=record.company,
                    industry=record.industry,
                    lang=record.lang,
                    status=record.status,
                    current_stage=record.current_stage,
                    failed_stage=record.failed_stage,
                    created_at=record.created_at,
                    started_at=record.started_at,
                    ended_at=record.ended_at,
                    duration_s=record.duration_s,
                    errors_json=(
                        json.dumps(record.errors, ensure_ascii=False)
                        if record.errors
                        else None
                    ),
                    usage_json=(
                        json.dumps(record.usage, ensure_ascii=False)
                        if record.usage
                        else None
                    ),
                    article_counts_json=(
                        json.dumps(
                            record.article_counts, ensure_ascii=False
                        )
                        if record.article_counts
                        else None
                    ),
                    proposal_points_count=record.proposal_points_count,
                    proposal_md=record.proposal_md,
                    output_dir=record.output_dir,
                    claude_model=record.claude_model,
                )
            )
            session.commit()

    def list_persisted(self, *, limit: int = 200) -> list[dict[str, Any]]:
        """Return the terminal-run snapshots from the DB (newest first).

        Returns `[]` when the store isn't wired to a session factory
        (CLI / unit-test mode). The Web UI is expected to merge this
        with `self.list()` for the run-history page; that merge lives
        at the route layer, not here.
        """
        if self._sf is None:
            return []
        from src.api.models.run import Run

        with self._sf() as session:
            rows = session.scalars(
                sa.select(Run)
                .order_by(Run.created_at.desc())
                .limit(limit)
            ).all()
        out: list[dict[str, Any]] = []
        for r in rows:
            try:
                errors = json.loads(r.errors_json) if r.errors_json else []
            except json.JSONDecodeError:
                errors = []
            try:
                usage = json.loads(r.usage_json) if r.usage_json else {}
            except json.JSONDecodeError:
                usage = {}
            try:
                article_counts = (
                    json.loads(r.article_counts_json)
                    if r.article_counts_json
                    else {}
                )
            except json.JSONDecodeError:
                article_counts = {}
            out.append(
                {
                    "run_id": r.run_id,
                    "company": r.company,
                    "industry": r.industry,
                    "lang": r.lang,
                    "status": r.status,
                    "current_stage": r.current_stage,
                    "failed_stage": r.failed_stage,
                    "created_at": r.created_at,
                    "started_at": r.started_at,
                    "ended_at": r.ended_at,
                    "duration_s": r.duration_s,
                    "errors": errors,
                    "usage": usage,
                    "article_counts": article_counts,
                    "proposal_points_count": r.proposal_points_count,
                    "proposal_md": r.proposal_md,
                    "output_dir": r.output_dir,
                    "claude_model": r.claude_model,
                    "_source": "persisted",
                }
            )
        return out


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
    """Phase 13B M7b — ORM-backed CRUD over the `targets` table.

    Public method shapes preserved from Phase 10 P10-1: every call still
    returns a `dict[str, Any]` with `aliases` already decoded from the
    `aliases_json` TEXT column. Routes and Web UI don't change.

    Stateless except for the session factory — every method opens its
    own short-lived Session, mirroring the original "connection per
    call" pattern so the store stays safe to share across worker threads.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        aliases_raw = row.aliases_json
        try:
            aliases = json.loads(aliases_raw) if aliases_raw else []
        except json.JSONDecodeError:
            aliases = []
        return {
            "id": row.id,
            "name": row.name,
            "industry": row.industry,
            "aliases": aliases,
            "notes": row.notes,
            "stage": row.stage,
            "created_from": row.created_from,
            "discovery_candidate_id": row.discovery_candidate_id,
            "last_run_id": row.last_run_id,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    def list(self) -> list[dict[str, Any]]:
        from src.api.models.target import Target

        with self._sf() as session:
            rows = session.scalars(
                sa.select(Target).order_by(Target.id.desc())
            ).all()
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
        from src.api.models.target import Target

        ts = _now_iso()
        aliases_json = json.dumps(aliases or [], ensure_ascii=False)
        with self._sf() as session:
            t = Target(
                name=name,
                industry=industry,
                aliases_json=aliases_json,
                notes=notes,
                stage=stage,
                created_from=created_from,
                discovery_candidate_id=discovery_candidate_id,
                last_run_id=last_run_id,
                created_at=ts,
                updated_at=ts,
            )
            session.add(t)
            session.commit()
            session.refresh(t)
            return self._row_to_dict(t)

    def get(self, target_id: int) -> dict[str, Any] | None:
        from src.api.models.target import Target

        with self._sf() as session:
            t = session.get(Target, target_id)
            return self._row_to_dict(t) if t else None

    def update(self, target_id: int, **fields: Any) -> dict[str, Any] | None:
        from src.api.models.target import Target

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
        with self._sf() as session:
            t = session.get(Target, target_id)
            if t is None:
                return None
            for k, v in col_map.items():
                setattr(t, k, v)
            session.commit()
            session.refresh(t)
            return self._row_to_dict(t)

    def delete(self, target_id: int) -> bool:
        from src.api.models.target import Target

        with self._sf() as session:
            t = session.get(Target, target_id)
            if t is None:
                return False
            session.delete(t)
            session.commit()
            return True


class DiscoveryStore:
    """Phase 13B M7c — ORM-backed discovery_runs + discovery_candidates CRUD.

    In-memory event log preserved verbatim (it's still the SSE-polled
    source for in-flight runs); only the SQLite paths move to ORM.
    `regions` round-trip via `_encode_regions_column` / `_decode_regions_column`
    so the legacy compat shim for "any"/"ko"/"us"/"eu"/"global" values is
    unchanged.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory
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
        try:
            usage = json.loads(row.usage_json) if row.usage_json else {}
        except json.JSONDecodeError:
            usage = {}
        regions = _decode_regions_column(row.region)
        weights_applied: dict[str, float] | None = None
        if row.weights_snapshot_json:
            try:
                parsed = json.loads(row.weights_snapshot_json)
                if isinstance(parsed, dict):
                    weights_applied = {
                        str(k): float(v) for k, v in parsed.items()
                    }
            except (json.JSONDecodeError, TypeError, ValueError):
                weights_applied = None
        return {
            "run_id": row.run_id,
            "generated_at": row.generated_at,
            "seed_doc_count": row.seed_doc_count or 0,
            "seed_chunk_count": row.seed_chunk_count or 0,
            "seed_summary": row.seed_summary,
            "profile": row.profile or "",
            "regions": regions,
            "lang": row.lang or "en",
            "namespace": row.namespace or "default",
            "status": row.status or "queued",
            "started_at": row.started_at,
            "ended_at": row.ended_at,
            "failed_stage": row.failed_stage,
            "error_message": row.error_message,
            "source_yaml_path": row.source_yaml_path,
            "claude_model": row.claude_model,
            "weights_applied": weights_applied,
            "usage": usage,
            "created_at": row.created_at,
        }

    def list_runs(self) -> list[dict[str, Any]]:
        from src.api.models.discovery import DiscoveryCandidate, DiscoveryRun

        with self._sf() as session:
            rows = session.scalars(
                sa.select(DiscoveryRun).order_by(DiscoveryRun.created_at.desc())
            ).all()
            results: list[dict[str, Any]] = []
            for r in rows:
                d = self._run_row_to_dict(r)
                tier_rows = session.execute(
                    sa.select(
                        DiscoveryCandidate.tier,
                        sa.func.count().label("n"),
                    )
                    .where(DiscoveryCandidate.run_id == d["run_id"])
                    .group_by(DiscoveryCandidate.tier)
                ).all()
                d["candidate_count"] = sum(int(cr.n) for cr in tier_rows)
                d["tier_distribution"] = {
                    cr.tier: int(cr.n) for cr in tier_rows
                }
                results.append(d)
        return results

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        from src.api.models.discovery import DiscoveryRun

        with self._sf() as session:
            r = session.get(DiscoveryRun, run_id)
            return self._run_row_to_dict(r) if r else None

    def create_run(
        self,
        *,
        run_id: str,
        generated_at: str,
        namespace: str,
        profile: str,
        regions: list[str],
        lang: str,
        seed_summary: str | None,
        claude_model: str | None = None,
    ) -> dict[str, Any]:
        from src.api.models.discovery import DiscoveryRun

        ts = _now_iso()
        region_blob = _encode_regions_column(regions)
        with self._sf() as session:
            r = DiscoveryRun(
                run_id=run_id,
                generated_at=generated_at,
                namespace=namespace,
                profile=profile,
                region=region_blob,
                lang=lang,
                seed_summary=seed_summary,
                status="queued",
                usage_json="{}",
                claude_model=claude_model,
                created_at=ts,
            )
            session.add(r)
            session.commit()
            session.refresh(r)
            return self._run_row_to_dict(r)

    def update_weights_snapshot(
        self, run_id: str, weights: dict[str, float]
    ) -> None:
        """Persist the normalized weight vector after final scoring.

        Failures don't propagate — candidates are already stored, the
        snapshot is a nice-to-have for past-run audit.
        """
        from src.api.models.discovery import DiscoveryRun

        try:
            blob = json.dumps(weights, separators=(",", ":"))
        except (TypeError, ValueError):
            return
        with self._sf() as session:
            r = session.get(DiscoveryRun, run_id)
            if r is None:
                return
            r.weights_snapshot_json = blob
            session.commit()

    def update_run(self, run_id: str, **fields: Any) -> dict[str, Any] | None:
        from src.api.models.discovery import DiscoveryRun

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
        with self._sf() as session:
            r = session.get(DiscoveryRun, run_id)
            if r is None:
                return None
            for k, v in col_map.items():
                setattr(r, k, v)
            session.commit()
            session.refresh(r)
            return self._run_row_to_dict(r)

    def delete_run(self, run_id: str) -> bool:
        from src.api.models.discovery import DiscoveryRun

        with self._sf() as session:
            r = session.get(DiscoveryRun, run_id)
            if r is None:
                return False
            session.delete(r)
            session.commit()
            return True

    # ── Candidates ────────────────────────────────────────────────────

    @staticmethod
    def _cand_row_to_dict(row: Any) -> dict[str, Any]:
        try:
            scores = json.loads(row.scores_json) if row.scores_json else {}
        except json.JSONDecodeError:
            scores = {}
        return {
            "id": row.id,
            "run_id": row.run_id,
            "name": row.name,
            "industry": row.industry,
            "scores": scores,
            "final_score": float(row.final_score or 0.0),
            "tier": row.tier or "C",
            "rationale": row.rationale,
            "status": row.status or "active",
            "updated_at": row.updated_at,
        }

    def list_candidates(self, run_id: str) -> list[dict[str, Any]]:
        from src.api.models.discovery import DiscoveryCandidate

        with self._sf() as session:
            rows = session.scalars(
                sa.select(DiscoveryCandidate)
                .where(DiscoveryCandidate.run_id == run_id)
                .order_by(
                    DiscoveryCandidate.final_score.desc(),
                    DiscoveryCandidate.id.asc(),
                )
            ).all()
        return [self._cand_row_to_dict(r) for r in rows]

    def get_candidate(self, candidate_id: int) -> dict[str, Any] | None:
        from src.api.models.discovery import DiscoveryCandidate

        with self._sf() as session:
            c = session.get(DiscoveryCandidate, candidate_id)
            return self._cand_row_to_dict(c) if c else None

    def insert_candidates(
        self, run_id: str, candidates: list[dict[str, Any]]
    ) -> None:
        from src.api.models.discovery import DiscoveryCandidate

        if not candidates:
            return
        ts = _now_iso()
        with self._sf() as session:
            for c in candidates:
                session.add(
                    DiscoveryCandidate(
                        run_id=run_id,
                        name=c["name"],
                        industry=c["industry"],
                        scores_json=json.dumps(
                            c.get("scores", {}), ensure_ascii=False
                        ),
                        final_score=float(c.get("final_score", 0.0)),
                        tier=c.get("tier", "C"),
                        rationale=c.get("rationale"),
                        status=c.get("status", "active"),
                        updated_at=ts,
                    )
                )
            session.commit()

    def update_candidate(
        self, candidate_id: int, **fields: Any
    ) -> dict[str, Any] | None:
        from src.api.models.discovery import DiscoveryCandidate

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
        with self._sf() as session:
            c = session.get(DiscoveryCandidate, candidate_id)
            if c is None:
                return None
            for k, v in col_map.items():
                setattr(c, k, v)
            session.commit()
            session.refresh(c)
            return self._cand_row_to_dict(c)

    def delete_candidate(self, candidate_id: int) -> bool:
        from src.api.models.discovery import DiscoveryCandidate

        with self._sf() as session:
            c = session.get(DiscoveryCandidate, candidate_id)
            if c is None:
                return False
            session.delete(c)
            session.commit()
            return True

    def bulk_update_tiers(
        self,
        updates: list[tuple[int, float, str]],  # (id, final_score, tier)
    ) -> None:
        from src.api.models.discovery import DiscoveryCandidate

        if not updates:
            return
        ts = _now_iso()
        with self._sf() as session:
            for cid, score, tier in updates:
                c = session.get(DiscoveryCandidate, cid)
                if c is None:
                    continue
                c.final_score = score
                c.tier = tier
                c.updated_at = ts
            session.commit()


class InteractionStore:
    """Phase 13B M7b — ORM-backed CRUD + LIKE search over `interactions`.

    Captured BD touchpoints (call/meeting/email/note) live here. The
    schema lets `target_id` be NULL so a free-text "I called Acme today"
    note works even before the company is registered as a Target. The
    LIKE search scans `company_name`, `raw_text`, and `contact_role` so
    "find every interaction that mentions Stripe" works without joins.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        return {
            "id": row.id,
            "target_id": row.target_id,
            "company_name": row.company_name,
            "kind": row.kind,
            "occurred_at": row.occurred_at,
            "outcome": row.outcome,
            "raw_text": row.raw_text,
            "contact_role": row.contact_role,
            "created_at": row.created_at,
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
        from src.api.models.interaction import Interaction

        ts = _now_iso()
        with self._sf() as session:
            i = Interaction(
                target_id=target_id,
                company_name=company_name,
                kind=kind,
                occurred_at=occurred_at,
                outcome=outcome,
                raw_text=raw_text,
                contact_role=contact_role,
                created_at=ts,
            )
            session.add(i)
            session.commit()
            session.refresh(i)
            return self._row_to_dict(i)

    def get(self, interaction_id: int) -> dict[str, Any] | None:
        from src.api.models.interaction import Interaction

        with self._sf() as session:
            i = session.get(Interaction, interaction_id)
            return self._row_to_dict(i) if i else None

    def list(
        self,
        *,
        company: str | None = None,
        target_id: int | None = None,
        q: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        from src.api.models.interaction import Interaction

        stmt = sa.select(Interaction)
        if company:
            stmt = stmt.where(Interaction.company_name == company)
        if target_id is not None:
            stmt = stmt.where(Interaction.target_id == target_id)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(
                sa.or_(
                    Interaction.company_name.like(like),
                    Interaction.raw_text.like(like),
                    Interaction.contact_role.like(like),
                )
            )
        stmt = stmt.order_by(
            Interaction.occurred_at.desc(), Interaction.id.desc()
        ).limit(limit)
        with self._sf() as session:
            rows = session.scalars(stmt).all()
        return [self._row_to_dict(r) for r in rows]

    def update(
        self, interaction_id: int, **fields: Any
    ) -> dict[str, Any] | None:
        from src.api.models.interaction import Interaction

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
        with self._sf() as session:
            i = session.get(Interaction, interaction_id)
            if i is None:
                return None
            for k, v in col_map.items():
                setattr(i, k, v)
            session.commit()
            session.refresh(i)
            return self._row_to_dict(i)

    def delete(self, interaction_id: int) -> bool:
        from src.api.models.interaction import Interaction

        with self._sf() as session:
            i = session.get(Interaction, interaction_id)
            if i is None:
                return False
            session.delete(i)
            session.commit()
            return True


class NewsStore:
    """Phase 13B M7c — ORM-backed CRUD over `news_runs`.

    One row per refresh task: queued / running / completed / failed
    status with cached `articles_json` blob (raw Brave hits + per-article
    meta). The UI reads `latest_for_namespace()` for the cache hit on
    `/news/today`, and `get(task_id)` for the polling hook after
    `POST /news/refresh`.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        try:
            articles = json.loads(row.articles_json or "[]")
        except (TypeError, json.JSONDecodeError):
            articles = []
        try:
            usage = json.loads(row.usage_json or "{}")
        except (TypeError, json.JSONDecodeError):
            usage = {}
        return {
            "task_id": row.task_id,
            "namespace": row.namespace,
            "generated_at": row.generated_at,
            "seed_summary": row.seed_summary,
            "seed_query": row.seed_query,
            "lang": row.lang,
            "days": row.days,
            "status": row.status,
            "article_count": row.article_count,
            "started_at": row.started_at,
            "ended_at": row.ended_at,
            "error_message": row.error_message,
            "sonnet_summary": row.sonnet_summary,
            "ttl_hours": row.ttl_hours,
            "articles": articles,
            "usage": usage,
            "created_at": row.created_at,
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
        from src.api.models.news_run import NewsRun

        ts = _now_iso()
        with self._sf() as session:
            r = NewsRun(
                task_id=task_id,
                namespace=namespace,
                generated_at=ts,
                seed_summary=seed_summary,
                seed_query=seed_query,
                articles_json="[]",
                lang=lang,
                days=days,
                status="queued",
                article_count=0,
                ttl_hours=ttl_hours,
                created_at=ts,
            )
            session.add(r)
            session.commit()
            session.refresh(r)
            return self._row_to_dict(r)

    def update(self, task_id: str, **fields: Any) -> dict[str, Any] | None:
        from src.api.models.news_run import NewsRun

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
        with self._sf() as session:
            r = session.get(NewsRun, task_id)
            if r is None:
                return None
            for k, v in col_map.items():
                setattr(r, k, v)
            session.commit()
            session.refresh(r)
            return self._row_to_dict(r)

    def get(self, task_id: str) -> dict[str, Any] | None:
        from src.api.models.news_run import NewsRun

        with self._sf() as session:
            r = session.get(NewsRun, task_id)
            return self._row_to_dict(r) if r else None

    def latest_for_namespace(
        self, namespace: str, *, status: str | None = "completed"
    ) -> dict[str, Any] | None:
        from src.api.models.news_run import NewsRun

        stmt = sa.select(NewsRun).where(NewsRun.namespace == namespace)
        if status:
            stmt = stmt.where(NewsRun.status == status)
        stmt = stmt.order_by(NewsRun.generated_at.desc()).limit(1)
        with self._sf() as session:
            r = session.scalar(stmt)
            return self._row_to_dict(r) if r else None

    def list(
        self, *, namespace: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        from src.api.models.news_run import NewsRun

        stmt = sa.select(NewsRun)
        if namespace:
            stmt = stmt.where(NewsRun.namespace == namespace)
        stmt = stmt.order_by(NewsRun.generated_at.desc()).limit(limit)
        with self._sf() as session:
            rows = session.scalars(stmt).all()
        return [self._row_to_dict(r) for r in rows]


class WorkspaceStore:
    """Phase 13B M7a — ORM-backed CRUD over the `workspaces` table.

    Ports the Phase 11 raw-sqlite WorkspaceStore to SQLAlchemy so the
    same code can target Postgres in Phase 13B. Public method shapes are
    unchanged — every method still returns `dict[str, Any]` rows so
    routes / `src/rag/workspaces.py` don't need to change.

    The built-in `default` workspace is seeded by `init_db` and protected
    from deletion. External workspaces let users register arbitrary local
    paths (e.g. D:\\my-docs\\) as additional roots in the RAG tree.

    Slug is auto-generated from label; collisions get -2/-3 suffixes.
    abs_path is validated (absolute + exists + is_dir + not inside the
    project's data/ directory). abs_path is immutable post-create — only
    label can be patched.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        # Accept both ORM model instances and bare result rows.
        if hasattr(row, "_mapping"):
            m = row._mapping
            return {
                "id": m["id"],
                "slug": m["slug"],
                "label": m["label"],
                "abs_path": m["abs_path"],
                "is_builtin": bool(m["is_builtin"]),
                "created_at": m["created_at"],
                "updated_at": m["updated_at"],
            }
        return {
            "id": row.id,
            "slug": row.slug,
            "label": row.label,
            "abs_path": row.abs_path,
            "is_builtin": bool(row.is_builtin),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
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

    def _next_slug(self, session: Session, label: str) -> str:
        from src.api.models.workspace import Workspace

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
            exists = session.scalar(
                sa.select(Workspace.id).where(Workspace.slug == candidate)
            )
            if exists is None and candidate not in reserved_ns:
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
        from src.api.models.workspace import Workspace

        with self._sf() as session:
            rows = session.scalars(
                sa.select(Workspace).order_by(
                    Workspace.is_builtin.desc(), Workspace.id.asc()
                )
            ).all()
        return [self._row_to_dict(r) for r in rows]

    def create(self, *, label: str, abs_path: str) -> dict[str, Any]:
        from src.api.models.workspace import Workspace

        resolved = self._validate_abs_path(abs_path)
        ts = _now_iso()
        with self._sf() as session:
            slug = self._next_slug(session, label)
            ws = Workspace(
                slug=slug,
                label=label,
                abs_path=str(resolved),
                is_builtin=False,
                created_at=ts,
                updated_at=ts,
            )
            session.add(ws)
            try:
                session.commit()
            except IntegrityError as e:
                session.rollback()
                # abs_path UNIQUE collision — another workspace already
                # registered this exact directory.
                raise ValueError(
                    f"abs_path is already registered as a workspace: {abs_path}"
                ) from e
            session.refresh(ws)
            return self._row_to_dict(ws)

    def get(self, workspace_id: int) -> dict[str, Any] | None:
        from src.api.models.workspace import Workspace

        with self._sf() as session:
            ws = session.get(Workspace, workspace_id)
            return self._row_to_dict(ws) if ws else None

    def get_by_slug(self, slug: str) -> dict[str, Any] | None:
        from src.api.models.workspace import Workspace

        with self._sf() as session:
            ws = session.scalar(
                sa.select(Workspace).where(Workspace.slug == slug)
            )
            return self._row_to_dict(ws) if ws else None

    def update(
        self, workspace_id: int, *, label: str | None = None
    ) -> dict[str, Any] | None:
        from src.api.models.workspace import Workspace

        # Only label is mutable. abs_path is intentionally immutable —
        # changing it would orphan the workspace's vectorstore directory
        # and confuse existing manifests.
        if label is None:
            return self.get(workspace_id)
        with self._sf() as session:
            ws = session.get(Workspace, workspace_id)
            if ws is None:
                return None
            ws.label = label
            ws.updated_at = _now_iso()
            session.commit()
            session.refresh(ws)
            return self._row_to_dict(ws)

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

        from src.api.models.rag_summary import RagSummary
        from src.api.models.workspace import Workspace

        slug: str | None = None
        removed = False
        with self._sf() as session:
            ws = session.get(Workspace, workspace_id)
            if ws is None:
                return False
            if ws.is_builtin:
                raise ValueError(
                    "the built-in `default` workspace cannot be deleted"
                )
            slug = ws.slug
            if wipe_index:
                session.execute(
                    sa.delete(RagSummary).where(RagSummary.ws_slug == slug)
                )
            session.delete(ws)
            session.commit()
            removed = True
        # Wipe the vectorstore on-disk AFTER the DB commit so a tree-walk
        # failure never leaves the registry pointing at a half-removed dir.
        if removed and wipe_index and slug is not None:
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


class RagSummaryStore:
    """Phase 13B M7a — ORM-backed CRUD over `rag_summaries`.

    Replaces the inline raw-sqlite helpers that lived in `routes/rag.py`
    (`_get_cached_summary`, `_upsert_summary`, `_delete_namespace_summaries`).
    The route module now goes through this store so legacy SQLite databases
    and Phase 13B+ Postgres databases speak the same dialect.

    Upsert uses DELETE-then-INSERT rather than `INSERT OR REPLACE` because
    legacy databases (pre-P11-2) still hold the original `(namespace, path)`
    PK — `INSERT OR REPLACE` would honor that PK and clobber other
    workspaces' rows for the same (ns, path). The DELETE narrows to the
    triple (ws_slug, namespace, path), matching the post-P11-2 PK shape.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    def get(
        self, ws_slug: str, namespace: str, path: str
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Return (row_as_dict, indexed_at_at_generation) or (None, None)."""
        from src.api.models.rag_summary import RagSummary

        with self._sf() as session:
            row = session.scalar(
                sa.select(RagSummary).where(
                    RagSummary.ws_slug == ws_slug,
                    RagSummary.namespace == namespace,
                    RagSummary.path == path,
                )
            )
            if row is None:
                return None, None
            return self._row_to_dict(row), row.indexed_at_at_generation

    def upsert(
        self,
        *,
        ws_slug: str,
        namespace: str,
        path: str,
        summary: str,
        lang: str,
        model: str | None,
        usage: dict[str, int] | None,
        chunk_count: int,
        chunks_in_namespace: int,
        indexed_at_at_generation: str | None,
        generated_at: str,
    ) -> None:
        from src.api.models.rag_summary import RagSummary

        usage_blob = (
            json.dumps(usage or {}, ensure_ascii=False)
            if usage is not None
            else None
        )
        with self._sf() as session:
            session.execute(
                sa.delete(RagSummary).where(
                    RagSummary.ws_slug == ws_slug,
                    RagSummary.namespace == namespace,
                    RagSummary.path == path,
                )
            )
            session.add(
                RagSummary(
                    ws_slug=ws_slug,
                    namespace=namespace,
                    path=path,
                    summary=summary,
                    lang=lang,
                    model=model,
                    usage_json=usage_blob,
                    chunk_count=chunk_count,
                    chunks_in_namespace=chunks_in_namespace,
                    indexed_at_at_generation=indexed_at_at_generation,
                    generated_at=generated_at,
                )
            )
            session.commit()

    def delete_namespace(self, ws_slug: str, namespace: str) -> None:
        from src.api.models.rag_summary import RagSummary

        with self._sf() as session:
            session.execute(
                sa.delete(RagSummary).where(
                    RagSummary.ws_slug == ws_slug,
                    RagSummary.namespace == namespace,
                )
            )
            session.commit()

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        usage_raw = row.usage_json or "{}"
        try:
            usage = json.loads(usage_raw)
        except (TypeError, json.JSONDecodeError):
            usage = {}
        return {
            "ws_slug": row.ws_slug,
            "namespace": row.namespace,
            "path": row.path,
            "summary": row.summary or "",
            "lang": row.lang,
            "model": row.model,
            "usage": usage if isinstance(usage, dict) else {},
            "chunk_count": int(row.chunk_count or 0),
            "chunks_in_namespace": int(row.chunks_in_namespace or 0),
            "indexed_at_at_generation": row.indexed_at_at_generation,
            "generated_at": row.generated_at,
        }


_run_store: RunStore | None = None
_ingest_store: IngestStore | None = None
_target_store: TargetStore | None = None
_discovery_store: DiscoveryStore | None = None
_news_store: NewsStore | None = None
_interaction_store: InteractionStore | None = None
_workspace_store: WorkspaceStore | None = None
_rag_summary_store: "RagSummaryStore | None" = None


def get_run_store() -> RunStore:
    """Return the process-wide RunStore.

    Phase 13C M9 — wired to the same ORM session factory as the other
    stores so terminal runs get a metadata snapshot persisted in the
    `runs` table. The in-memory dict + event log behavior is unchanged.
    """
    global _run_store
    if _run_store is None:
        _run_store = RunStore(_orm.get_session_factory())
    return _run_store


def get_ingest_store() -> IngestStore:
    global _ingest_store
    if _ingest_store is None:
        _ingest_store = IngestStore()
    return _ingest_store


def get_target_store() -> TargetStore:
    """Return a TargetStore bound to the configured database URL.

    Phase 13B M7b — switched to an ORM session factory keyed by
    `settings.database_url`. Tests should follow the standard
    `reset_api_settings_cache()` + `reset_stores()` pattern.
    """
    global _target_store
    if _target_store is None:
        _target_store = TargetStore(_orm.get_session_factory())
    return _target_store


def get_discovery_store() -> DiscoveryStore:
    """Return a DiscoveryStore bound to the configured database URL.

    Phase 13B M7c — ORM session factory; in-memory event log lives on
    the singleton so the legacy SSE consumer behavior is preserved
    across the port.
    """
    global _discovery_store
    if _discovery_store is None:
        _discovery_store = DiscoveryStore(_orm.get_session_factory())
    return _discovery_store


def get_news_store() -> NewsStore:
    """Return a NewsStore bound to the configured database URL.

    Phase 13B M7c — ORM session factory.
    """
    global _news_store
    if _news_store is None:
        _news_store = NewsStore(_orm.get_session_factory())
    return _news_store


def get_interaction_store() -> InteractionStore:
    """Return an InteractionStore bound to the configured database URL.

    Phase 13B M7b — ORM session factory; see `get_target_store`.
    """
    global _interaction_store
    if _interaction_store is None:
        _interaction_store = InteractionStore(_orm.get_session_factory())
    return _interaction_store


def get_workspace_store() -> WorkspaceStore:
    """Return a WorkspaceStore bound to the configured database URL.

    Phase 13B M7a — switched from raw-sqlite path to an ORM session
    factory keyed by `settings.database_url`. Tests that swap
    `API_APP_DB` / `DATABASE_URL` should call `reset_stores()` after
    `reset_api_settings_cache()` so the next access rebuilds the
    singleton against the new URL.
    """
    global _workspace_store
    if _workspace_store is None:
        _workspace_store = WorkspaceStore(_orm.get_session_factory())
    return _workspace_store


def get_rag_summary_store() -> RagSummaryStore:
    """Return a RagSummaryStore bound to the configured database URL."""
    global _rag_summary_store
    if _rag_summary_store is None:
        _rag_summary_store = RagSummaryStore(_orm.get_session_factory())
    return _rag_summary_store


def reset_stores() -> None:
    """Test hook — drop cached singletons so each test starts empty."""
    global _run_store, _ingest_store, _target_store, _discovery_store
    global _news_store, _interaction_store, _workspace_store
    global _rag_summary_store
    _run_store = None
    _ingest_store = None
    _target_store = None
    _discovery_store = None
    _news_store = None
    _interaction_store = None
    _workspace_store = None
    _rag_summary_store = None
    # Also drop cached ORM session factories so the next get_*_store()
    # picks up a fresh API_APP_DB / DATABASE_URL.
    _orm.reset_session_factories()
