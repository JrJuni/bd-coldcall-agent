"""Phase 10 P10-6 — /interactions endpoints (사업 기록).

CRUD over the `interactions` table with `?company=` exact-match and
`?q=` LIKE search. The schema lets `target_id` be NULL so a free-text
"called Acme today" note works even before the company is registered as
a Target.

Module-attribute access only (`from src.api import store as _store`).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status

from src.api import store as _store
from src.api.schemas import (
    InteractionCreate,
    InteractionListResponse,
    InteractionSummary,
    InteractionUpdate,
)


_LOGGER = logging.getLogger(__name__)

router = APIRouter()


@router.get("/interactions", response_model=InteractionListResponse)
async def list_interactions(
    company: str | None = None,
    target_id: int | None = None,
    q: str | None = None,
    limit: int = 200,
) -> InteractionListResponse:
    if limit <= 0 or limit > 1000:
        raise HTTPException(
            status_code=422, detail="limit must be in [1, 1000]"
        )
    rows = _store.get_interaction_store().list(
        company=company.strip() if company else None,
        target_id=target_id,
        q=q.strip() if q else None,
        limit=limit,
    )
    return InteractionListResponse(
        interactions=[InteractionSummary(**r) for r in rows]
    )


@router.post(
    "/interactions",
    response_model=InteractionSummary,
    status_code=status.HTTP_201_CREATED,
)
async def create_interaction(payload: InteractionCreate) -> InteractionSummary:
    row = _store.get_interaction_store().create(**payload.model_dump())
    return InteractionSummary(**row)


@router.get(
    "/interactions/{interaction_id}", response_model=InteractionSummary
)
async def get_interaction(interaction_id: int) -> InteractionSummary:
    row = _store.get_interaction_store().get(interaction_id)
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"interaction {interaction_id} not found"
        )
    return InteractionSummary(**row)


@router.patch(
    "/interactions/{interaction_id}", response_model=InteractionSummary
)
async def patch_interaction(
    interaction_id: int, payload: InteractionUpdate
) -> InteractionSummary:
    fields = payload.model_dump(exclude_unset=True)
    row = _store.get_interaction_store().update(interaction_id, **fields)
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"interaction {interaction_id} not found"
        )
    return InteractionSummary(**row)


@router.delete(
    "/interactions/{interaction_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_interaction(interaction_id: int) -> None:
    ok = _store.get_interaction_store().delete(interaction_id)
    if not ok:
        raise HTTPException(
            status_code=404, detail=f"interaction {interaction_id} not found"
        )
