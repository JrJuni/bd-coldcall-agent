"""Phase 7 — Pydantic request/response schemas for the FastAPI routes.

Kept separate from `src/graph/state.py` (TypedDict for the internal
LangGraph state) because the wire format is stable public API and the
internal state accumulates messier artifacts (ProposalPoint, Article,
RetrievedChunk) that we don't want to leak unchanged over HTTP.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


RunState = Literal["queued", "running", "failed", "completed"]


class RunCreateRequest(BaseModel):
    company: str = Field(..., min_length=1, max_length=200)
    industry: str = Field(..., min_length=1, max_length=200)
    lang: Literal["en", "ko"] = "en"
    top_k: int | None = Field(default=None, ge=1, le=50)


class RunCreateResponse(BaseModel):
    run_id: str
    status: RunState
    created_at: str


class RunSummary(BaseModel):
    run_id: str
    company: str
    industry: str
    lang: str
    status: RunState
    current_stage: str | None = None
    stages_completed: list[str] = Field(default_factory=list)
    failed_stage: str | None = None
    created_at: str
    started_at: str | None = None
    ended_at: str | None = None
    duration_s: float | None = None
    errors: list[dict[str, Any]] = Field(default_factory=list)
    usage: dict[str, int] = Field(default_factory=dict)
    article_counts: dict[str, int] = Field(default_factory=dict)
    proposal_points_count: int = 0
    proposal_md: str | None = None
    output_dir: str | None = None


class RunListResponse(BaseModel):
    runs: list[RunSummary]


class IngestStatus(BaseModel):
    manifest_path: str
    manifest_exists: bool
    version: int | None = None
    updated_at: str | None = None
    document_count: int = 0
    chunk_count: int = 0
    by_source_type: dict[str, int] = Field(default_factory=dict)


class IngestTriggerRequest(BaseModel):
    notion: bool = False
    force: bool = False
    dry_run: bool = False


class IngestTriggerResponse(BaseModel):
    task_id: str
    status: Literal["queued", "running", "completed", "failed"]
    message: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok"]
    warmup_skipped: bool
    exaone_loaded: bool
    embedder_loaded: bool
