"""Phase 5 — AgentState TypedDict carried through the LangGraph pipeline.

`total=False` because most fields accumulate as the graph progresses —
`search_node` writes `articles`, `preprocess_node` overwrites them with
translated/tagged versions, etc. The initial state only needs the three
user-facing inputs (company, industry, lang) plus a run_id/output_dir
stamped by the orchestrator.

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

    # per-stage artifacts
    articles: list[Article]
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
        "articles": [],
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
