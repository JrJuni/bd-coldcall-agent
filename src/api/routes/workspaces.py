"""Phase 11 P11-0 — /workspaces CRUD endpoints.

Backed by `WorkspaceStore` (SQLite via `src/api/db.py`). Lets the UI
register external local paths (e.g. D:\\my-docs\\) as additional roots
in the RAG Folders tree.

The built-in `default` workspace is seeded on boot and protected from
deletion (DELETE returns 400). abs_path is immutable post-create — only
label can be patched. Slug is auto-derived from label with -2/-3 suffix
on collision.

DO NOT rule: this file imports `src.api.store as _store` so tests can
swap the singleton without touching this module.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from src.api import store as _store
from src.api.schemas import (
    WorkspaceCreate,
    WorkspaceListResponse,
    WorkspaceSummary,
    WorkspaceUpdate,
)


_LOGGER = logging.getLogger(__name__)


router = APIRouter()


def _to_summary(row: dict) -> WorkspaceSummary:
    return WorkspaceSummary(**row)


@router.get("/workspaces", response_model=WorkspaceListResponse)
async def list_workspaces() -> WorkspaceListResponse:
    store = _store.get_workspace_store()
    rows = store.list()
    return WorkspaceListResponse(workspaces=[_to_summary(r) for r in rows])


@router.post("/workspaces", response_model=WorkspaceSummary, status_code=201)
async def create_workspace(payload: WorkspaceCreate) -> WorkspaceSummary:
    store = _store.get_workspace_store()
    try:
        row = store.create(label=payload.label, abs_path=payload.abs_path)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _to_summary(row)


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceSummary)
async def get_workspace(workspace_id: int) -> WorkspaceSummary:
    store = _store.get_workspace_store()
    row = store.get(workspace_id)
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"workspace {workspace_id} not found"
        )
    return _to_summary(row)


@router.patch("/workspaces/{workspace_id}", response_model=WorkspaceSummary)
async def patch_workspace(
    workspace_id: int, payload: WorkspaceUpdate
) -> WorkspaceSummary:
    store = _store.get_workspace_store()
    row = store.update(workspace_id, label=payload.label)
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"workspace {workspace_id} not found"
        )
    return _to_summary(row)


@router.delete("/workspaces/{workspace_id}", status_code=204)
async def delete_workspace(
    workspace_id: int, wipe_index: bool = False
) -> None:
    """Remove a workspace from the RAG tree.

    The registered abs_path (source files) is NEVER touched — only the
    workspace registry row is removed. When `wipe_index=true`, the
    workspace's vectorstore directory + cached AI summaries are also
    removed; when false (default), they stay on disk so re-adding the
    same workspace later restores the index for free.
    """
    store = _store.get_workspace_store()
    try:
        ok = store.delete(workspace_id, wipe_index=wipe_index)
    except ValueError as e:
        # Built-in workspace deletion attempt.
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(
            status_code=404, detail=f"workspace {workspace_id} not found"
        )
    return None
