"""Phase 7 — /ingest endpoints (minimal MVP).

Scope is intentionally read-only + trigger-only:
- `GET /ingest/status` — reads `manifest.json` from the vectorstore path
  in settings and summarizes document / chunk counts. No store traversal
  (Chroma queries are pricier to run synchronously on an HTTP request).
- `POST /ingest` — triggers `src.rag.indexer.main()` in the background,
  returning a task_id for status polling.
- `GET /ingest/tasks/{task_id}` — poll the task record.

Full RAG management UI (upload / delete / reindex subset) is Phase 7+
backlog in `docs/status.md`.
"""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException

from src.api import runner as _runner
from src.api.schemas import (
    IngestStatus,
    IngestTriggerRequest,
    IngestTriggerResponse,
)
from src.api.store import get_ingest_store
from src.config import loader as _config_loader
from src.rag.namespace import (
    DEFAULT_NAMESPACE,
    MANIFEST_FILENAME,
    vectorstore_root_for,
)


_LOGGER = logging.getLogger(__name__)

router = APIRouter()


def _manifest_path(namespace: str = DEFAULT_NAMESPACE) -> Path:
    settings = _config_loader.get_settings()
    vs_path = Path(settings.rag.vectorstore_path)
    return vectorstore_root_for(vs_path, namespace) / MANIFEST_FILENAME


@router.get("/ingest/status", response_model=IngestStatus)
async def ingest_status(namespace: str = DEFAULT_NAMESPACE) -> IngestStatus:
    path = _manifest_path(namespace)
    if not path.exists():
        return IngestStatus(
            manifest_path=str(path),
            manifest_exists=False,
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _LOGGER.warning("ingest_status: could not read manifest: %s", exc)
        return IngestStatus(
            manifest_path=str(path),
            manifest_exists=True,
        )

    documents = raw.get("documents") or {}
    by_type: dict[str, int] = {}
    chunk_total = 0
    for entry in documents.values():
        st = entry.get("source_type") or "unknown"
        by_type[st] = by_type.get(st, 0) + 1
        chunk_total += int(entry.get("chunk_count") or 0)

    return IngestStatus(
        manifest_path=str(path),
        manifest_exists=True,
        version=raw.get("version"),
        updated_at=raw.get("updated_at"),
        document_count=len(documents),
        chunk_count=chunk_total,
        by_source_type=by_type,
    )


@router.post("/ingest", response_model=IngestTriggerResponse, status_code=202)
async def trigger_ingest(
    payload: IngestTriggerRequest,
    background_tasks: BackgroundTasks,
) -> IngestTriggerResponse:
    store = get_ingest_store()
    task_id = uuid.uuid4().hex
    task = store.create(task_id=task_id, params=payload.model_dump())
    background_tasks.add_task(
        _runner.execute_ingest,
        task_id=task_id,
        params=payload.model_dump(),
    )
    return IngestTriggerResponse(
        task_id=task.task_id,
        status=task.status,  # type: ignore[arg-type]
        message="Ingest task queued",
    )


@router.get("/ingest/tasks/{task_id}", response_model=IngestTriggerResponse)
async def get_ingest_task(task_id: str) -> IngestTriggerResponse:
    store = get_ingest_store()
    task = store.get(task_id)
    if task is None:
        raise HTTPException(
            status_code=404, detail=f"task_id {task_id!r} not found"
        )
    return IngestTriggerResponse(
        task_id=task.task_id,
        status=task.status,  # type: ignore[arg-type]
        message=task.message,
    )
