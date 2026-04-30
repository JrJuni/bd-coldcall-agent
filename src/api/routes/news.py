"""Phase 10 P10-5 — Daily News endpoints.

- ``POST /news/refresh`` — kick off a Brave news search, returns 202 + task_id
- ``GET  /news/today?namespace=`` — latest cached completed run for a
  namespace, 404 if none yet (UI shows refresh CTA)
- ``GET  /news/runs/{task_id}`` — poll a single task

Module-attribute access only (``from src.api import runner as _runner`` and
``from src.api import store as _store``) so tests can monkeypatch
``execute_news_refresh`` and Brave clients without rebinding imports.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from src.api import runner as _runner
from src.api import store as _store
from src.api.schemas import (
    NewsArticle,
    NewsRefreshRequest,
    NewsRefreshResponse,
    NewsRunDetail,
    NewsRunListResponse,
    NewsRunSummary,
)


_LOGGER = logging.getLogger(__name__)

router = APIRouter()


def _validate_namespace(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="namespace required")
    if not all(c.isalnum() or c in ("-", "_") for c in name):
        raise HTTPException(
            status_code=422,
            detail=(
                f"namespace {name!r} contains invalid characters; "
                "use only [A-Za-z0-9_-]"
            ),
        )
    return name


def _record_to_summary(record: dict, *, include_articles: bool):
    base = NewsRunSummary(
        task_id=record["task_id"],
        namespace=record["namespace"],
        generated_at=record["generated_at"],
        seed_summary=record.get("seed_summary"),
        seed_query=record.get("seed_query"),
        lang=record.get("lang") or "en",
        days=int(record.get("days") or 30),
        status=record["status"],
        article_count=int(record.get("article_count") or 0),
        started_at=record.get("started_at"),
        ended_at=record.get("ended_at"),
        error_message=record.get("error_message"),
        sonnet_summary=record.get("sonnet_summary"),
        ttl_hours=int(record.get("ttl_hours") or 12),
        usage=record.get("usage") or {},
    )
    if not include_articles:
        return base
    articles = [
        NewsArticle(**{k: a.get(k) for k in NewsArticle.model_fields})
        for a in (record.get("articles") or [])
    ]
    return NewsRunDetail(**base.model_dump(), articles=articles)


def _make_task_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"news-{stamp}-{uuid.uuid4().hex[:6]}"


@router.post(
    "/news/refresh",
    response_model=NewsRefreshResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def refresh_news(
    payload: NewsRefreshRequest,
    background_tasks: BackgroundTasks,
) -> NewsRefreshResponse:
    namespace = _validate_namespace(payload.namespace)
    store = _store.get_news_store()
    task_id = _make_task_id()
    store.create(
        task_id=task_id,
        namespace=namespace,
        seed_query=payload.seed_query,
        seed_summary=payload.seed_summary,
        lang=payload.lang,
        days=payload.days,
    )
    background_tasks.add_task(
        _runner.execute_news_refresh,
        task_id=task_id,
        namespace=namespace,
        seed_query=payload.seed_query,
        seed_summary=payload.seed_summary,
        lang=payload.lang,
        days=payload.days,
        count=payload.count,
    )
    return NewsRefreshResponse(
        task_id=task_id, status="queued", namespace=namespace
    )


@router.get("/news/today", response_model=NewsRunDetail)
async def news_today(namespace: str = "default") -> NewsRunDetail:
    namespace = _validate_namespace(namespace)
    store = _store.get_news_store()
    record = store.latest_for_namespace(namespace)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"no completed news run for namespace {namespace!r} yet; "
                "POST /news/refresh first"
            ),
        )
    return _record_to_summary(record, include_articles=True)


@router.get("/news/runs/{task_id}", response_model=NewsRunDetail)
async def get_news_run(task_id: str) -> NewsRunDetail:
    store = _store.get_news_store()
    record = store.get(task_id)
    if record is None:
        raise HTTPException(
            status_code=404, detail=f"task_id {task_id!r} not found"
        )
    return _record_to_summary(record, include_articles=True)


@router.get("/news/runs", response_model=NewsRunListResponse)
async def list_news_runs(
    namespace: str | None = None, limit: int = 20
) -> NewsRunListResponse:
    if namespace is not None:
        namespace = _validate_namespace(namespace)
    store = _store.get_news_store()
    rows = store.list(namespace=namespace, limit=limit)
    return NewsRunListResponse(
        runs=[_record_to_summary(r, include_articles=False) for r in rows]
    )
