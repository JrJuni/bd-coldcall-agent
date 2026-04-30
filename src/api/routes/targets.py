"""Phase 10 P10-1 — /targets endpoints (CRUD only).

Backed by `TargetStore` (SQLite via `src/api/db.py`). Discovery promotion
lands in P10-2; this PR is intentionally limited to manual create / edit
/ delete so the pipeline tab can be exercised standalone.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from src.api import store as _store
from src.api.schemas import (
    TargetCreate,
    TargetListResponse,
    TargetSummary,
    TargetUpdate,
)


_LOGGER = logging.getLogger(__name__)


router = APIRouter()


def _to_summary(row: dict) -> TargetSummary:
    return TargetSummary(**row)


@router.get("/targets", response_model=TargetListResponse)
async def list_targets() -> TargetListResponse:
    store = _store.get_target_store()
    rows = store.list()
    return TargetListResponse(targets=[_to_summary(r) for r in rows])


@router.post("/targets", response_model=TargetSummary, status_code=201)
async def create_target(payload: TargetCreate) -> TargetSummary:
    store = _store.get_target_store()
    row = store.create(
        name=payload.name,
        industry=payload.industry,
        aliases=payload.aliases,
        notes=payload.notes,
        stage=payload.stage,
        created_from="manual",
    )
    return _to_summary(row)


@router.get("/targets/{target_id}", response_model=TargetSummary)
async def get_target(target_id: int) -> TargetSummary:
    store = _store.get_target_store()
    row = store.get(target_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"target {target_id} not found")
    return _to_summary(row)


@router.patch("/targets/{target_id}", response_model=TargetSummary)
async def patch_target(target_id: int, payload: TargetUpdate) -> TargetSummary:
    store = _store.get_target_store()
    row = store.update(
        target_id,
        name=payload.name,
        industry=payload.industry,
        aliases=payload.aliases,
        notes=payload.notes,
        stage=payload.stage,
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"target {target_id} not found")
    return _to_summary(row)


@router.delete("/targets/{target_id}", status_code=204)
async def delete_target(target_id: int) -> None:
    store = _store.get_target_store()
    if not store.delete(target_id):
        raise HTTPException(status_code=404, detail=f"target {target_id} not found")
    return None
