"""Phase 5 — AgentState TypedDict carried through the LangGraph pipeline.

`total=False` because most fields accumulate as the graph progresses —
article lists live under three stage-specific keys (`searched_articles`,
`fetched_articles`, `processed_articles`) so a failed run always preserves
the last successful stage's output for post-mortem. The initial state only
needs the three user-facing inputs (company, industry, lang) plus a
run_id/output_dir stamped by the orchestrator.

Usage accounting is intentionally flat — four Anthropic token counters
summed across synthesize + draft — so `merge_usage` is a pure reducer and
the run summary JSON stays grep-friendly.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, TypedDict

from src.llm.claude_client import USAGE_KEYS
from src.llm.proposal_schemas import ProposalPoint
from src.rag.types import RetrievedChunk
from src.search.base import Article


__all__ = [
    "AgentState",
    "RunStatus",
    "USAGE_KEYS",
    "empty_usage",
    "latest_articles",
    "merge_usage",
    "new_state",
]


RunStatus = Literal["running", "failed", "completed"]


class AgentState(TypedDict, total=False):
    # inputs
    company: str
    industry: str
    lang: Literal["en", "ko"]
    top_k: int

    # per-stage article artifacts — each node writes to its own key so
    # failure post-mortem can see exactly where the pipeline stopped.
    searched_articles: list[Article]
    fetched_articles: list[Article]
    processed_articles: list[Article]
    tech_chunks: list[RetrievedChunk]
    proposal_points: list[ProposalPoint]
    proposal_md: str

    # meta
    errors: list[dict[str, Any]]
    usage: dict[str, int]
    stages_completed: list[str]
    failed_stage: str | None
    current_stage: str | None
    status: RunStatus
    run_id: str
    output_dir: Path
    started_at: float
    ended_at: float


def empty_usage() -> dict[str, int]:
    return {k: 0 for k in USAGE_KEYS}


def merge_usage(
    existing: dict[str, int] | None,
    addition: dict[str, int] | None,
) -> dict[str, int]:
    """Sum two usage dicts into a new dict with all four keys present."""
    out = empty_usage()
    for src in (existing, addition):
        if not src:
            continue
        for k in USAGE_KEYS:
            out[k] += int(src.get(k, 0) or 0)
    return out


def latest_articles(state: "AgentState") -> list[Article]:
    """Return the most recent article list seen — processed > fetched > searched.

    Used by `persist_node` to serialize whatever survived (the later stages
    are strict supersets of the earlier ones) and by CLI summaries that
    want to report "the articles we ended up with."
    """
    for key in ("processed_articles", "fetched_articles", "searched_articles"):
        value = state.get(key)  # type: ignore[call-overload]
        if value:
            return list(value)
    return []


def new_state(
    *,
    company: str,
    industry: str,
    lang: Literal["en", "ko"],
    output_dir: Path,
    run_id: str,
    top_k: int | None = None,
    started_at: float | None = None,
) -> AgentState:
    """Build the seed state the orchestrator passes into `graph.invoke()`."""
    state: AgentState = {
        "company": company,
        "industry": industry,
        "lang": lang,
        "searched_articles": [],
        "fetched_articles": [],
        "processed_articles": [],
        "tech_chunks": [],
        "proposal_points": [],
        "proposal_md": "",
        "errors": [],
        "usage": empty_usage(),
        "stages_completed": [],
        "status": "running",
        "current_stage": None,
        "run_id": run_id,
        "output_dir": output_dir,
    }
    if top_k is not None:
        state["top_k"] = top_k
    if started_at is not None:
        state["started_at"] = started_at
    return state
