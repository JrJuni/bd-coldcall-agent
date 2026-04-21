"""Phase 5 — LangGraph node adapters.

Each node is a thin wrapper that:
  1. reads the inputs it needs from `AgentState`,
  2. calls the corresponding Phase 1-4 function,
  3. returns a partial state dict for LangGraph to merge.

The `@_stage` decorator catches any exception, records a `StageError` into
`state.errors`, and sets `failed_stage` so the graph's conditional router can
short-circuit straight to `persist_node`. Happy-path nodes append the stage
name to `stages_completed`.

Heavy lifting lives in the original modules (search/bilingual, fetcher,
preprocess, retriever, synthesize, draft) — nodes never duplicate logic.
Tests monkeypatch the module-level imports below.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.config.loader import get_secrets, get_settings
from src.graph.errors import StageError
from src.graph.state import AgentState, merge_usage
from src.llm.draft import draft_proposal
from src.llm.preprocess import preprocess_articles
from src.llm.synthesize import synthesize_proposal_points
from src.rag.retriever import retrieve
from src.search.bilingual import bilingual_news_search
from src.search.brave import BraveSearch
from src.search.fetcher import fetch_bodies_parallel


_LOGGER = logging.getLogger(__name__)


STAGE_SEARCH = "search"
STAGE_FETCH = "fetch"
STAGE_PREPROCESS = "preprocess"
STAGE_RETRIEVE = "retrieve"
STAGE_SYNTHESIZE = "synthesize"
STAGE_DRAFT = "draft"
STAGE_PERSIST = "persist"


def _stage(name: str) -> Callable[[Callable[[AgentState], dict]], Callable[[AgentState], dict]]:
    """Wrap a node so exceptions become `failed_stage` + StageError in state.

    Successful nodes get their name appended to `stages_completed`.
    `persist_node` is exempt from failed_stage short-circuit — it always runs
    as the terminal. For the decorator that means: if persist itself raises
    we still record but don't set failed_stage (no-op route).
    """
    def decorator(fn: Callable[[AgentState], dict]) -> Callable[[AgentState], dict]:
        def wrapped(state: AgentState) -> dict:
            try:
                patch = fn(state)
            except Exception as e:  # noqa: BLE001 — fail-fast boundary
                _LOGGER.exception("[%s] node failed", name)
                err = StageError.from_exception(name, e)
                existing_errors = list(state.get("errors") or [])
                existing_errors.append(err.to_dict())
                return {
                    "errors": existing_errors,
                    "failed_stage": name,
                }
            # Bookkeeping: stages_completed is append-only, deduped.
            stages = list(state.get("stages_completed") or [])
            if name not in stages:
                stages.append(name)
            patch.setdefault("stages_completed", stages)
            return patch
        wrapped.__name__ = fn.__name__
        wrapped.__doc__ = fn.__doc__
        return wrapped
    return decorator


# ---------------------------------------------------------------------------
# Node implementations
# ---------------------------------------------------------------------------


@_stage(STAGE_SEARCH)
def search_node(state: AgentState) -> dict:
    """Brave search for recent articles about the target company."""
    settings = get_settings()
    secrets = get_secrets()
    if not secrets.brave_search_api_key:
        raise RuntimeError("BRAVE_SEARCH_API_KEY not set in .env")

    company = state["company"]
    lang = state.get("lang", settings.search.default_lang)
    days = settings.search.days
    count = settings.search.max_articles

    use_bilingual = (lang == "ko" and settings.search.bilingual_on_ko)

    with BraveSearch(secrets.brave_search_api_key) as client:
        if use_bilingual:
            articles, _meta = bilingual_news_search(
                client,
                company,
                primary_lang=lang,
                translations_ko_to_en=settings.search.translations_ko_to_en,
                days=days,
                total_count=count,
                min_foreign_ratio=settings.search.min_foreign_ratio,
            )
        else:
            articles = client.search(
                company, lang=lang, days=days, kind="news", count=count
            )

    _LOGGER.info("[search] company=%s lang=%s → %d articles", company, lang, len(articles))
    return {"articles": articles}


@_stage(STAGE_FETCH)
def fetch_node(state: AgentState) -> dict:
    """Fill article bodies via trafilatura + ThreadPool."""
    articles = list(state.get("articles") or [])
    if not articles:
        return {"articles": articles}
    enriched = fetch_bodies_parallel(articles)
    full = sum(1 for a in enriched if a.body_source == "full")
    snippet = sum(1 for a in enriched if a.body_source == "snippet")
    _LOGGER.info(
        "[fetch] total=%d full=%d snippet_fallback=%d",
        len(enriched), full, snippet,
    )
    return {"articles": enriched}


@_stage(STAGE_PREPROCESS)
def preprocess_node(state: AgentState) -> dict:
    """Translate → tag → dedup via local Exaone + bge-m3."""
    articles = list(state.get("articles") or [])
    if not articles:
        return {"articles": articles}
    lang = state.get("lang")
    kept, meta = preprocess_articles(articles, target_lang=lang)
    _LOGGER.info(
        "[preprocess] in=%d translated=%d tagged=%d kept=%d",
        meta.get("n_input", 0),
        meta.get("n_translated", 0),
        meta.get("n_tagged", 0),
        meta.get("n_output", 0),
    )
    return {"articles": kept}


@_stage(STAGE_RETRIEVE)
def retrieve_node(state: AgentState) -> dict:
    """Pull top-k tech-doc chunks for the target."""
    settings = get_settings()
    top_k = state.get("top_k") or settings.llm.claude_rag_top_k
    company = state["company"]
    chunks = retrieve(company, top_k=top_k)
    _LOGGER.info("[retrieve] query=%s top_k=%d → %d chunks", company, top_k, len(chunks))
    return {"tech_chunks": chunks}


@_stage(STAGE_SYNTHESIZE)
def synthesize_node(state: AgentState) -> dict:
    """Sonnet synthesis of ProposalPoint list; merges usage into state."""
    points, call_usage = synthesize_proposal_points(
        list(state.get("articles") or []),
        list(state.get("tech_chunks") or []),
        target_company=state["company"],
        industry=state.get("industry", ""),
        lang=state.get("lang", "en"),
    )
    _LOGGER.info("[synthesize] got %d proposal points", len(points))
    merged = merge_usage(state.get("usage"), call_usage)
    return {"proposal_points": points, "usage": merged}


@_stage(STAGE_DRAFT)
def draft_node(state: AgentState) -> dict:
    """Sonnet draft of the Markdown brief; merges usage into state."""
    points = list(state.get("proposal_points") or [])
    articles = list(state.get("articles") or [])
    draft, call_usage = draft_proposal(
        points,
        articles,
        target_company=state["company"],
        lang=state.get("lang", "en"),
    )
    _LOGGER.info("[draft] %d words", len(draft.markdown.split()))
    merged = merge_usage(state.get("usage"), call_usage)
    return {"proposal_md": draft.markdown, "usage": merged}


# ---------------------------------------------------------------------------
# Persist — serialization helpers + terminal node
# ---------------------------------------------------------------------------


def _to_jsonable(value: Any) -> Any:
    """Recursive dataclass / pydantic / datetime / Path serializer."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "model_dump"):
        return _to_jsonable(value.model_dump())
    if is_dataclass(value) and not isinstance(value, type):
        return _to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    return str(value)


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_to_jsonable(obj), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def persist_node(state: AgentState) -> dict:
    """Terminal — write proposal.md + intermediates + run_summary.

    Runs unconditionally (even after a failed upstream stage) so partial
    state is always on disk for post-mortem. Not wrapped by `@_stage`
    because its own failures shouldn't trigger another stage transition.
    """
    output_dir = Path(state["output_dir"])
    intermediate = output_dir / "intermediate"
    intermediate.mkdir(parents=True, exist_ok=True)

    # Always write what we have — even partial.
    articles = state.get("articles") or []
    if articles:
        _write_json(intermediate / "articles_after_preprocess.json", articles)

    tech_chunks = state.get("tech_chunks") or []
    if tech_chunks:
        _write_json(intermediate / "tech_chunks.json", tech_chunks)

    points = state.get("proposal_points") or []
    if points:
        _write_json(intermediate / "points.json", points)

    md = state.get("proposal_md") or ""
    md_path: Path | None = None
    if md.strip():
        md_path = output_dir / "proposal.md"
        md_path.write_text(md, encoding="utf-8")

    stages = list(state.get("stages_completed") or [])
    if STAGE_PERSIST not in stages:
        stages.append(STAGE_PERSIST)

    started = state.get("started_at")
    duration_s = (time.perf_counter() - started) if started is not None else None
    summary = {
        "run_id": state.get("run_id"),
        "company": state.get("company"),
        "industry": state.get("industry"),
        "lang": state.get("lang"),
        "duration_s": duration_s,
        "usage": state.get("usage") or {},
        "errors": state.get("errors") or [],
        "failed_stage": state.get("failed_stage"),
        "stages_completed": stages,
        "proposal_md_path": str(md_path) if md_path else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(intermediate / "run_summary.json", summary)

    return {"stages_completed": stages}


def route_after_stage(state: AgentState) -> str:
    """Conditional-edge router — 'persist' if any stage failed, else 'continue'."""
    return "persist" if state.get("failed_stage") else "continue"
