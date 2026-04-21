"""Phase 7 — /runs endpoints.

- `POST /runs` — queue a new pipeline run. BackgroundTasks dispatches
  `execute_run` in anyio's worker thread so the HTTP request returns
  immediately with the assigned `run_id`.
- `GET /runs/{run_id}` — current record snapshot.
- `GET /runs` — list recent runs (in-memory, process-local).
- `GET /runs/{run_id}/events` — SSE stream; yields every event since
  the last seen seq number, terminates when the run reaches a terminal
  state and no more events remain.

The stream polls at ~150ms intervals. Since the event log only grows
(7 stages + ~5 meta events), polling is dramatically simpler than a
coroutine-threadsafe queue for MVP scale.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from src.api import runner as _runner
from src.api.schemas import (
    RunCreateRequest,
    RunCreateResponse,
    RunListResponse,
    RunSummary,
)
from src.api.store import RunRecord, get_run_store


_LOGGER = logging.getLogger(__name__)
SSE_POLL_INTERVAL_S = 0.15


router = APIRouter()


def _make_run_id(company: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{company}"


def _record_to_summary(record: RunRecord, *, include_md: bool) -> RunSummary:
    return RunSummary(
        run_id=record.run_id,
        company=record.company,
        industry=record.industry,
        lang=record.lang,
        status=record.status,  # type: ignore[arg-type]
        current_stage=record.current_stage,
        stages_completed=list(record.stages_completed),
        failed_stage=record.failed_stage,
        created_at=record.created_at,
        started_at=record.started_at,
        ended_at=record.ended_at,
        duration_s=record.duration_s,
        errors=list(record.errors),
        usage=dict(record.usage),
        article_counts=dict(record.article_counts),
        proposal_points_count=record.proposal_points_count,
        proposal_md=record.proposal_md if include_md else None,
        output_dir=record.output_dir,
    )


@router.post("/runs", response_model=RunCreateResponse, status_code=202)
async def create_run(
    payload: RunCreateRequest,
    background_tasks: BackgroundTasks,
    request: Request,
) -> RunCreateResponse:
    store = get_run_store()
    run_id = _make_run_id(payload.company)
    record = store.create(
        run_id=run_id,
        company=payload.company,
        industry=payload.industry,
        lang=payload.lang,
    )
    record.append_event("run_queued", {"run_id": run_id})

    checkpointer = getattr(request.app.state, "checkpointer", None)

    background_tasks.add_task(
        _runner.execute_run,
        run_id=run_id,
        company=payload.company,
        industry=payload.industry,
        lang=payload.lang,
        top_k=payload.top_k,
        checkpointer=checkpointer,
    )

    return RunCreateResponse(
        run_id=run_id,
        status=record.status,  # type: ignore[arg-type]
        created_at=record.created_at,
    )


@router.get("/runs", response_model=RunListResponse)
async def list_runs() -> RunListResponse:
    store = get_run_store()
    # Insertion order is newest-last; reverse for a newest-first listing.
    # Sorting by created_at is unreliable when multiple runs are created
    # within the same second.
    records = list(reversed(store.list()))
    return RunListResponse(
        runs=[_record_to_summary(r, include_md=False) for r in records]
    )


@router.get("/runs/{run_id}", response_model=RunSummary)
async def get_run(run_id: str) -> RunSummary:
    store = get_run_store()
    record = store.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"run_id {run_id!r} not found")
    return _record_to_summary(record, include_md=True)


@router.get("/runs/{run_id}/events")
async def run_events(run_id: str, request: Request):
    store = get_run_store()
    record = store.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"run_id {run_id!r} not found")

    async def generator() -> AsyncIterator[dict]:
        last_seq = 0
        while True:
            if await request.is_disconnected():
                return
            events = record.snapshot_events(since_seq=last_seq)
            for ev in events:
                last_seq = ev.seq
                yield {
                    "event": ev.kind,
                    "id": str(ev.seq),
                    "data": json.dumps(
                        {
                            "seq": ev.seq,
                            "ts": ev.ts,
                            "kind": ev.kind,
                            "payload": ev.payload,
                        },
                        ensure_ascii=False,
                    ),
                }
            if record.status in ("completed", "failed") and not record.snapshot_events(
                since_seq=last_seq
            ):
                return
            await asyncio.sleep(SSE_POLL_INTERVAL_S)

    return EventSourceResponse(generator())
