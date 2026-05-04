"""Phase 7 — Pydantic request/response schemas for the FastAPI routes.

Kept separate from `src/graph/state.py` (TypedDict for the internal
LangGraph state) because the wire format is stable public API and the
internal state accumulates messier artifacts (ProposalPoint, Article,
RetrievedChunk) that we don't want to leak unchanged over HTTP.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


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
    claude_model: str | None = None
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
    workspace: str = Field(default="default", min_length=1, max_length=80)
    namespace: str = Field(default="default", min_length=1, max_length=80)


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


# ── Phase 11 P11-0 — Workspaces ──────────────────────────────────────────


class WorkspaceCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=80)
    abs_path: str = Field(..., min_length=1, max_length=500)


class WorkspaceUpdate(BaseModel):
    # abs_path is intentionally not patchable — see WorkspaceStore.update().
    label: str | None = Field(default=None, min_length=1, max_length=80)


class WorkspaceSummary(BaseModel):
    id: int
    slug: str
    label: str
    abs_path: str
    is_builtin: bool
    created_at: str
    updated_at: str


class WorkspaceListResponse(BaseModel):
    workspaces: list[WorkspaceSummary]


# ── Phase 10 P10-2a — RAG namespaces ─────────────────────────────────────


class RagNamespaceSummary(BaseModel):
    name: str
    document_count: int = 0
    chunk_count: int = 0
    updated_at: str | None = None
    by_source_type: dict[str, int] = Field(default_factory=dict)
    is_default: bool = False
    # True when at least one file in the namespace's docs root has been
    # added or modified since its last indexed_at — i.e. Re-index needed.
    needs_reindex: bool = False


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


# ── Phase 10 P10-3+ — RAG folder browsing ───────────────────────────────


RagTreeEntryType = Literal["folder", "file"]


class RagTreeEntry(BaseModel):
    type: RagTreeEntryType
    name: str
    # File-only fields (None for folders).
    size_bytes: int | None = None
    modified_at: str | None = None
    extension: str | None = None
    indexed: bool | None = None
    chunk_count: int | None = None
    # Folder-only fields (None for files).
    child_count: int | None = None
    # Folder-only — True when any descendant file is missing from the
    # manifest or has mtime > its indexed_at.
    needs_reindex: bool | None = None


class RagTreeResponse(BaseModel):
    namespace: str
    path: str  # posix subpath relative to namespace root, "" = root
    parent: str | None = None
    entries: list[RagTreeEntry] = Field(default_factory=list)


class RagFolderCreate(BaseModel):
    path: str = Field(..., min_length=1, max_length=512)


class RagFolderActionResponse(BaseModel):
    namespace: str
    path: str
    removed: bool = False
    created: bool = False


class RagOpenFolderResponse(BaseModel):
    namespace: str
    path: str
    abs_path: str
    opened: bool


class RagRootOpenResponse(BaseModel):
    abs_path: str
    opened: bool


class RagRootFileListResponse(BaseModel):
    files: list[RagDocumentSummary] = Field(default_factory=list)


class RagSummaryRequest(BaseModel):
    path: str = ""
    lang: Literal["en", "ko"] = "ko"
    sample_size: int = Field(default=20, ge=1, le=80)
    max_tokens: int = Field(default=900, ge=100, le=4000)


class RagSummaryResponse(BaseModel):
    namespace: str
    path: str
    chunk_count: int  # how many chunks were sampled
    chunks_in_namespace: int  # total chunks available
    summary: str  # the LLM output (markdown bullets)
    model: str | None = None
    usage: dict[str, int] = Field(default_factory=dict)
    generated_at: str
    # True when the folder has been re-indexed since this summary was
    # generated — UI flips the "다시 생성" button to "Update ⚠".
    is_stale: bool = False


class RagSummaryCachedResponse(BaseModel):
    """Wrapper for GET /rag/namespaces/{ns}/summary — returns null when no
    cached summary exists for the (namespace, path) pair so the frontend
    can branch on a 200 + null payload instead of catching a 404."""

    summary: RagSummaryResponse | None = None


# ── Phase 10 P10-2b — Discovery ──────────────────────────────────────────


DiscoveryStatus = Literal["queued", "running", "completed", "failed"]
CandidateStatus = Literal["active", "archived", "promoted"]
TierLiteral = Literal["S", "A", "B", "C"]


# Phase 12 — region migrated from a 4-value Literal to a list of ISO 3166-1
# alpha-2 country codes (plus the wildcard "global"). Legacy single-value
# inputs ("any" / "ko" / "us" / "eu" / "global") are coerced for backward
# compat by `_coerce_legacy_region`.
_LEGACY_REGION_TO_LIST: dict[str, list[str]] = {
    "any": [],
    "global": ["global"],
    "ko": ["kr"],
    "us": ["us"],
    "eu": ["gb"],
}


def _normalize_regions_list(items: list[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        if not isinstance(raw, str):
            raise ValueError(f"region entries must be strings, got {raw!r}")
        s = raw.strip().lower()
        if not s or s == "any":
            continue
        if s == "global":
            code = "global"
        elif len(s) != 2 or not s.isalpha():
            raise ValueError(
                f"region must be ISO 3166-1 alpha-2 (e.g. 'us') or 'global', got {raw!r}"
            )
        else:
            code = s
        if code not in seen:
            seen.add(code)
            out.append(code)
    return out


def _normalize_seed_queries(items: list[Any]) -> list[str]:
    """Trim, lowercase-dedupe, and drop blanks from a list of seed queries.

    Order is preserved — the first occurrence of each unique (case-folded)
    keyword wins. Blank or whitespace-only entries are silently dropped.
    Phase 12: matches the chip-input pattern in the Discovery form, where
    duplicates are easy to introduce with `databricks, Databricks` etc.
    """
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        if not isinstance(raw, str):
            raise ValueError(
                f"seed_queries entries must be strings, got {raw!r}"
            )
        s = raw.strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


class DiscoveryRunCreate(BaseModel):
    namespace: str = Field(default="default", min_length=1, max_length=80)
    # Phase 12 — list of ISO 3166-1 alpha-2 codes (or "global"). Empty list
    # / None means "no region filter". Legacy `region` key in JSON is
    # accepted via a model_validator and folded into this field.
    regions: list[str] = Field(default_factory=list)
    product: str = Field(default="databricks", min_length=1, max_length=80)
    seed_summary: str | None = None
    # Phase 12 — list of RAG retrieve queries. Empty list / None → core
    # discover_targets default. Legacy `seed_query: str` JSON key is
    # accepted via a model_validator and wrapped into this list.
    seed_queries: list[str] = Field(default_factory=list)
    top_k: int | None = Field(default=None, ge=1, le=100)
    n_industries: int = Field(default=5, ge=1, le=20)
    n_per_industry: int = Field(default=5, ge=1, le=20)
    lang: Literal["en", "ko"] = "en"
    include_sector_leaders: bool = True

    @model_validator(mode="before")
    @classmethod
    def _absorb_legacy_region(cls, data: Any) -> Any:
        """Accept the pre-Phase-12 `region: <enum>` JSON key transparently.

        If both `region` and `regions` are present the explicit list wins.
        Legacy enum values map via _LEGACY_REGION_TO_LIST so a stored UI
        fixture sending `"region": "any"` still validates after the upgrade.
        """
        if not isinstance(data, dict):
            return data
        if "regions" in data and data["regions"] is not None:
            return data
        legacy = data.pop("region", None) if "region" in data else None
        if legacy is None:
            return data
        if isinstance(legacy, str):
            mapped = _LEGACY_REGION_TO_LIST.get(legacy.strip().lower())
            data["regions"] = list(mapped) if mapped is not None else [legacy]
        elif isinstance(legacy, list):
            data["regions"] = list(legacy)
        return data

    @model_validator(mode="before")
    @classmethod
    def _absorb_legacy_seed_query(cls, data: Any) -> Any:
        """Accept the pre-Phase-12 `seed_query: <str>` JSON key transparently.

        Old UIs and saved fixtures send a single seed_query string. We fold
        it into `seed_queries` as a 1-element list (or empty, if blank/null)
        unless the caller already provided an explicit `seed_queries`.
        """
        if not isinstance(data, dict):
            return data
        if "seed_queries" in data and data["seed_queries"] is not None:
            data.pop("seed_query", None)
            return data
        legacy = data.pop("seed_query", None) if "seed_query" in data else None
        if legacy is None:
            return data
        if isinstance(legacy, str):
            stripped = legacy.strip()
            data["seed_queries"] = [stripped] if stripped else []
        elif isinstance(legacy, list):
            data["seed_queries"] = list(legacy)
        return data

    @field_validator("regions", mode="before")
    @classmethod
    def _coerce_regions(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            v = [v]
        if not isinstance(v, list):
            raise ValueError(f"regions must be a list of strings, got {type(v).__name__}")
        return _normalize_regions_list(v)

    @field_validator("seed_queries", mode="before")
    @classmethod
    def _coerce_seed_queries(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            v = [v]
        if not isinstance(v, list):
            raise ValueError(
                f"seed_queries must be a list of strings, got {type(v).__name__}"
            )
        return _normalize_seed_queries(v)


class DiscoveryRunSummary(BaseModel):
    run_id: str
    generated_at: str
    status: DiscoveryStatus
    namespace: str
    product: str
    # Phase 12 — list of ISO alpha-2 codes; empty = no filter applied.
    regions: list[str] = Field(default_factory=list)
    lang: str
    seed_doc_count: int = 0
    seed_chunk_count: int = 0
    seed_summary: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    failed_stage: str | None = None
    error_message: str | None = None
    usage: dict[str, int] = Field(default_factory=dict)
    claude_model: str | None = None
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


# ── Phase 10 P10-6 — Interactions (사업 기록) ────────────────────────────


InteractionKind = Literal["call", "meeting", "email", "note"]
InteractionOutcome = Literal["positive", "neutral", "negative", "pending"]
INTERACTION_KINDS: tuple[str, ...] = ("call", "meeting", "email", "note")
INTERACTION_OUTCOMES: tuple[str, ...] = (
    "positive",
    "neutral",
    "negative",
    "pending",
)


class InteractionCreate(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=200)
    kind: InteractionKind = "note"
    occurred_at: str = Field(..., min_length=1, max_length=64)
    outcome: InteractionOutcome | None = None
    raw_text: str | None = Field(default=None, max_length=20_000)
    contact_role: str | None = Field(default=None, max_length=200)
    target_id: int | None = None


class InteractionUpdate(BaseModel):
    company_name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: InteractionKind | None = None
    occurred_at: str | None = Field(default=None, min_length=1, max_length=64)
    outcome: InteractionOutcome | None = None
    raw_text: str | None = Field(default=None, max_length=20_000)
    contact_role: str | None = Field(default=None, max_length=200)
    target_id: int | None = None


class InteractionSummary(BaseModel):
    id: int
    target_id: int | None = None
    company_name: str
    kind: InteractionKind
    occurred_at: str
    outcome: InteractionOutcome | None = None
    raw_text: str | None = None
    contact_role: str | None = None
    created_at: str


class InteractionListResponse(BaseModel):
    interactions: list[InteractionSummary]


# ── Phase 10 P10-7 — Settings ───────────────────────────────────────────


SettingsKind = Literal[
    "settings",
    "weights",
    "tier_rules",
    "competitors",
    "intent_tiers",
    "sector_leaders",
    "targets",
    "pricing",
    "cost_budget",
]
SETTINGS_KINDS: tuple[str, ...] = (
    "settings",
    "weights",
    "tier_rules",
    "competitors",
    "intent_tiers",
    "sector_leaders",
    "targets",
    "pricing",
    "cost_budget",
)


class SettingsRead(BaseModel):
    kind: SettingsKind
    path: str
    exists: bool
    raw_yaml: str = ""
    parsed: dict[str, Any] | None = None


class SettingsUpdate(BaseModel):
    raw_yaml: str = Field(..., max_length=200_000)


class SettingsKindList(BaseModel):
    kinds: list[SettingsKind]


class SecretsView(BaseModel):
    anthropic_api_key: bool
    brave_search_api_key: bool
    notion_token: bool


# ── Phase 10 P10-8 — Home dashboard ─────────────────────────────────────


class DashboardRecentRun(BaseModel):
    run_id: str
    company: str
    industry: str
    status: str
    created_at: str


class DashboardRecentDiscovery(BaseModel):
    run_id: str
    namespace: str
    product: str
    status: str
    candidate_count: int
    tier_distribution: dict[str, int]
    generated_at: str


class DashboardNewsMini(BaseModel):
    namespace: str
    generated_at: str
    article_count: int
    seed_query: str | None = None
    top_titles: list[str] = Field(default_factory=list)


class DashboardRagStatus(BaseModel):
    namespace: str
    document_count: int = 0
    chunk_count: int = 0
    is_indexed: bool = False


class DashboardCostSummary(BaseModel):
    """Phase 11+ — USD-centric. Token counts moved to /cost/summary."""

    this_month_usd: float = 0.0
    last_month_usd: float = 0.0
    cumulative_usd: float = 0.0
    cache_savings_usd: float = 0.0
    cache_savings_pct: float = 0.0
    monthly_budget_usd: float = 0.0
    used_pct: float = 0.0
    breached: bool = False
    over_budget: bool = False


class DashboardResponse(BaseModel):
    recent_runs: list[DashboardRecentRun] = Field(default_factory=list)
    recent_discovery: DashboardRecentDiscovery | None = None
    pipeline_by_stage: dict[str, int] = Field(default_factory=dict)
    rag: list[DashboardRagStatus] = Field(default_factory=list)
    news: DashboardNewsMini | None = None
    interactions_count: int = 0
    cost: DashboardCostSummary = Field(default_factory=DashboardCostSummary)
    generated_at: str


# ── Phase 11+ — Cost Explorer ───────────────────────────────────────────


class CostKpi(BaseModel):
    this_month_usd: float = 0.0
    last_month_usd: float = 0.0
    cumulative_usd: float = 0.0
    cache_savings_usd: float = 0.0
    cache_savings_pct: float = 0.0


class CostDailyPoint(BaseModel):
    date: str  # ISO YYYY-MM-DD
    usd: float


class CostBreakdownItem(BaseModel):
    label: str
    usd: float
    tokens: int


class CostPerUnit(BaseModel):
    per_proposal_usd: float | None = None
    per_discovery_target_usd: float | None = None


class CostBudgetState(BaseModel):
    monthly_usd: float
    used_usd: float
    used_pct: float
    warn_pct: float
    breached: bool
    over_budget: bool


class CostRecentRunTokens(BaseModel):
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0


class CostRecentRun(BaseModel):
    run_id: str
    created_at: str
    run_type: str
    model: str
    label: str
    tokens: CostRecentRunTokens
    usd: float


class CostSummaryResponse(BaseModel):
    kpi: CostKpi
    daily_series: list[CostDailyPoint] = Field(default_factory=list)
    by_model: list[CostBreakdownItem] = Field(default_factory=list)
    by_run_type: list[CostBreakdownItem] = Field(default_factory=list)
    per_unit: CostPerUnit = Field(default_factory=CostPerUnit)
    budget: CostBudgetState
    recent_runs: list[CostRecentRun] = Field(default_factory=list)
    days: int
    generated_at: str
