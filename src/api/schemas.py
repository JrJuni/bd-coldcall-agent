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


class RunUpdate(BaseModel):
    proposal_md: str | None = Field(default=None, max_length=200_000)


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


# ── Phase 10 — Targets (P10-1) ───────────────────────────────────────────

TargetStage = Literal[
    "planned", "contacted", "proposal_sent", "meeting", "won", "lost"
]
TARGET_STAGES: tuple[str, ...] = (
    "planned", "contacted", "proposal_sent", "meeting", "won", "lost"
)
CreatedFrom = Literal["manual", "discovery_promote"]


class TargetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    industry: str = Field(..., min_length=1, max_length=200)
    aliases: list[str] = Field(default_factory=list)
    notes: str | None = None
    stage: TargetStage = "planned"


class TargetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    industry: str | None = Field(default=None, min_length=1, max_length=200)
    aliases: list[str] | None = None
    notes: str | None = None
    stage: TargetStage | None = None


class TargetSummary(BaseModel):
    id: int
    name: str
    industry: str
    aliases: list[str] = Field(default_factory=list)
    notes: str | None = None
    stage: TargetStage
    created_from: CreatedFrom
    discovery_candidate_id: int | None = None
    last_run_id: str | None = None
    created_at: str
    updated_at: str


class TargetListResponse(BaseModel):
    targets: list[TargetSummary]


# ── Phase 10 P10-2a — RAG namespaces ─────────────────────────────────────


class RagNamespaceSummary(BaseModel):
    name: str
    document_count: int = 0
    chunk_count: int = 0
    updated_at: str | None = None
    by_source_type: dict[str, int] = Field(default_factory=dict)
    is_default: bool = False


class RagNamespaceListResponse(BaseModel):
    namespaces: list[RagNamespaceSummary]
    default: str


# ── Phase 10 P10-3 — RAG document management ────────────────────────────


class RagNamespaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)


class RagDocumentSummary(BaseModel):
    filename: str  # path relative to namespace docs root, forward slashes
    size_bytes: int
    modified_at: str | None = None
    extension: str
    indexed: bool = False
    chunk_count: int = 0


class RagDocumentListResponse(BaseModel):
    namespace: str
    documents: list[RagDocumentSummary]
    indexed_doc_count: int = 0


class RagDocumentUploadResponse(BaseModel):
    namespace: str
    filename: str
    size_bytes: int


class RagNamespaceDeleteResponse(BaseModel):
    name: str
    removed: bool


# ── Phase 10 P10-2b — Discovery ──────────────────────────────────────────


DiscoveryRegion = Literal["any", "ko", "us", "eu", "global"]
DiscoveryStatus = Literal["queued", "running", "completed", "failed"]
CandidateStatus = Literal["active", "archived", "promoted"]
TierLiteral = Literal["S", "A", "B", "C"]


class DiscoveryRunCreate(BaseModel):
    namespace: str = Field(default="default", min_length=1, max_length=80)
    region: DiscoveryRegion = "any"
    product: str = Field(default="databricks", min_length=1, max_length=80)
    seed_summary: str | None = None
    seed_query: str | None = None  # None → discover_targets default
    top_k: int | None = Field(default=None, ge=1, le=100)
    n_industries: int = Field(default=5, ge=1, le=20)
    n_per_industry: int = Field(default=5, ge=1, le=20)
    lang: Literal["en", "ko"] = "en"
    include_sector_leaders: bool = True


class DiscoveryRunSummary(BaseModel):
    run_id: str
    generated_at: str
    status: DiscoveryStatus
    namespace: str
    product: str
    region: DiscoveryRegion
    lang: str
    seed_doc_count: int = 0
    seed_chunk_count: int = 0
    seed_summary: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    failed_stage: str | None = None
    error_message: str | None = None
    usage: dict[str, int] = Field(default_factory=dict)
    created_at: str
    candidate_count: int = 0
    tier_distribution: dict[str, int] = Field(default_factory=dict)


class DiscoveryRunListResponse(BaseModel):
    runs: list[DiscoveryRunSummary]


class DiscoveryCandidate(BaseModel):
    id: int
    run_id: str
    name: str
    industry: str
    scores: dict[str, int]
    final_score: float
    tier: TierLiteral
    rationale: str | None = None
    status: CandidateStatus = "active"
    updated_at: str


class DiscoveryRunDetail(DiscoveryRunSummary):
    candidates: list[DiscoveryCandidate] = Field(default_factory=list)


class DiscoveryCandidateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    industry: str | None = Field(default=None, min_length=1, max_length=200)
    scores: dict[str, int] | None = None
    rationale: str | None = None
    status: CandidateStatus | None = None
    tier: TierLiteral | None = None  # manual tier override


class DiscoveryRecomputeRequest(BaseModel):
    weights: dict[str, float] | None = None  # 6-dim slider state from UI
    product: str | None = None  # fallback to weights.yaml::products.<name>


class DiscoveryRecomputeResponse(BaseModel):
    run_id: str
    candidates: list[DiscoveryCandidate]
    weights_applied: dict[str, float]
    tier_distribution: dict[str, int]


class DiscoveryPromoteResponse(BaseModel):
    candidate_id: int
    target_id: int
    candidate_status: CandidateStatus


# ── Phase 10 P10-5 — Daily News ─────────────────────────────────────────


NewsStatus = Literal["queued", "running", "completed", "failed"]


class NewsArticle(BaseModel):
    title: str
    url: str
    snippet: str | None = None
    hostname: str | None = None
    lang: str | None = None
    published: str | None = None


class NewsRefreshRequest(BaseModel):
    namespace: str = Field(default="default", min_length=1, max_length=80)
    seed_query: str = Field(..., min_length=1, max_length=200)
    lang: Literal["en", "ko"] = "en"
    days: int = Field(default=30, ge=1, le=365)
    count: int = Field(default=10, ge=1, le=20)
    seed_summary: str | None = None


class NewsRunSummary(BaseModel):
    task_id: str
    namespace: str
    generated_at: str
    seed_summary: str | None = None
    seed_query: str | None = None
    lang: str
    days: int
    status: NewsStatus
    article_count: int = 0
    started_at: str | None = None
    ended_at: str | None = None
    error_message: str | None = None
    sonnet_summary: str | None = None
    ttl_hours: int = 12
    usage: dict[str, int] = Field(default_factory=dict)


class NewsRunDetail(NewsRunSummary):
    articles: list[NewsArticle] = Field(default_factory=list)


class NewsRunListResponse(BaseModel):
    runs: list[NewsRunSummary]


class NewsRefreshResponse(BaseModel):
    task_id: str
    status: NewsStatus
    namespace: str
