"""Phase 7 — background execution adapters for /runs and /ingest.

Both functions run synchronously inside FastAPI `BackgroundTasks`, which
dispatches sync callables through anyio's worker thread pool. Progress
is streamed back to callers by mutating shared `RunStore`/`IngestStore`
records — SSE readers then poll the per-record event log on the event
loop. No cross-thread queues or coroutine threadsafe plumbing, because
the event log + record snapshot pattern is enough at MVP scale (one
background run at a time per run_id).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.api.store import (
    IngestStore,
    RunRecord,
    RunStore,
    get_ingest_store,
    get_run_store,
)

_LOGGER = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _article_counts(state: dict[str, Any]) -> dict[str, int]:
    return {
        "searched": len(state.get("searched_articles") or []),
        "fetched": len(state.get("fetched_articles") or []),
        "processed": len(state.get("processed_articles") or []),
    }


def execute_run(
    *,
    run_id: str,
    company: str,
    industry: str,
    lang: str,
    top_k: int | None,
    output_root: Path | None = None,
    checkpointer: Any | None = None,
    store: RunStore | None = None,
) -> None:
    """Drive the pipeline via `orchestrator.run_streaming` and mirror progress
    into the RunStore record so /runs/{id} and SSE can observe it.
    """
    from src.core import orchestrator as _orchestrator

    store = store or get_run_store()
    record = store.get(run_id)
    if record is None:
        _LOGGER.error("execute_run: run_id %s not found in store", run_id)
        return

    store.update(run_id, status="running", started_at=_now_iso())
    record.append_event("run_started", {"run_id": run_id, "company": company})

    final_state: dict[str, Any] | None = None
    prev_stages: set[str] = set()
    prev_stage: str | None = None

    try:
        for state in _orchestrator.run_streaming(
            company=company,
            industry=industry,
            lang=lang,  # type: ignore[arg-type]
            output_root=output_root,
            top_k=top_k,
            run_id=run_id,
            checkpointer=checkpointer,
        ):
            final_state = dict(state)
            stages = list(final_state.get("stages_completed") or [])
            current = final_state.get("current_stage")
            newly_done = [s for s in stages if s not in prev_stages]
            for s in newly_done:
                record.append_event("stage_completed", {"stage": s})
            if current != prev_stage and current:
                record.append_event("stage_started", {"stage": current})
            prev_stages = set(stages)
            prev_stage = current

            store.update(
                run_id,
                status=final_state.get("status") or "running",
                current_stage=current,
                stages_completed=stages,
                failed_stage=final_state.get("failed_stage"),
                usage=dict(final_state.get("usage") or {}),
                errors=list(final_state.get("errors") or []),
                article_counts=_article_counts(final_state),
                proposal_points_count=len(final_state.get("proposal_points") or []),
            )

        if final_state is not None:
            started = final_state.get("started_at")
            ended = final_state.get("ended_at")
            duration = (
                round(float(ended) - float(started), 3)
                if started is not None and ended is not None
                else None
            )
            status = final_state.get("status") or (
                "failed" if final_state.get("failed_stage") else "completed"
            )
            output_dir = final_state.get("output_dir")
            store.update(
                run_id,
                status=status,
                proposal_md=final_state.get("proposal_md") or None,
                output_dir=str(output_dir) if output_dir else None,
                ended_at=_now_iso(),
                duration_s=duration,
            )
            record.append_event(
                "run_completed" if status == "completed" else "run_failed",
                {
                    "status": status,
                    "failed_stage": final_state.get("failed_stage"),
                    "duration_s": duration,
                    "proposal_points_count": len(final_state.get("proposal_points") or []),
                },
            )
    except Exception as exc:
        _LOGGER.exception("execute_run: unhandled exception in pipeline")
        err = {
            "stage": "runner",
            "error_type": type(exc).__name__,
            "message": str(exc),
        }
        store.update(
            run_id,
            status="failed",
            failed_stage="runner",
            ended_at=_now_iso(),
            errors=list(record.errors) + [err],
        )
        record.append_event("run_failed", err)


def execute_ingest(
    *,
    task_id: str,
    params: dict[str, Any],
    store: IngestStore | None = None,
) -> None:
    """Invoke `src.rag.indexer.main` with argv derived from `params`.

    The indexer returns an int exit code; non-zero marks the task
    failed. Exceptions are caught and written to the task record so the
    endpoint always reports a definitive status.
    """
    from src.rag import indexer as _indexer

    store = store or get_ingest_store()
    task = store.get(task_id)
    if task is None:
        _LOGGER.error("execute_ingest: task_id %s not found", task_id)
        return

    store.update(task_id, status="running")

    argv: list[str] = []
    if params.get("notion"):
        argv.append("--notion")
    if params.get("force"):
        argv.append("--force")
    if params.get("dry_run"):
        argv.append("--dry-run")

    try:
        code = _indexer.main(argv)
    except Exception as exc:
        _LOGGER.exception("execute_ingest: indexer raised")
        store.update(
            task_id,
            status="failed",
            ended_at=_now_iso(),
            message=f"{type(exc).__name__}: {exc}",
        )
        return

    if code == 0:
        store.update(
            task_id,
            status="completed",
            ended_at=_now_iso(),
            message="Ingest finished",
        )
    else:
        store.update(
            task_id,
            status="failed",
            ended_at=_now_iso(),
            message=f"Indexer exited with code {code}",
        )
