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
from src.search import channels as _channels  # module-level import for monkeypatch safety
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
                    "current_stage": name,
                }
            # Bookkeeping: stages_completed is append-only, deduped.
            stages = list(state.get("stages_completed") or [])
            if name not in stages:
                stages.append(name)
            patch.setdefault("stages_completed", stages)
            patch.setdefault("current_stage", name)
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
    """Phase 8 — multi-channel Brave search (target / related / competitor).

    Per-channel failure is captured in `search_meta.channel_errors`; the
    node only fails if every channel raises (then the partial merge is
    empty and persist still happens via the conditional router).
    """
    settings = get_settings()
    secrets = get_secrets()
    if not secrets.brave_search_api_key:
        raise RuntimeError("BRAVE_SEARCH_API_KEY not set in .env")

    company = state["company"]
    lang = state.get("lang", settings.search.default_lang)

    articles, search_meta = _channels.run_all_channels(
        company=company,
        primary_lang=lang,
        settings=settings,
        brave_api_key=secrets.brave_search_api_key,
    )

    by_channel = search_meta.get("by_channel", {})
    counts = {
        name: meta.get("returned", 0) for name, meta in by_channel.items()
    }
    _LOGGER.info(
        "[search] company=%s lang=%s → target=%d related=%d competitor=%d "
        "(merged=%d after x-channel dedup)",
        company,
        lang,
        counts.get("target", 0),
        counts.get("related", 0),
        counts.get("competitor", 0),
        len(articles),
    )
    return {"searched_articles": articles, "search_meta": search_meta}


@_stage(STAGE_FETCH)
def fetch_node(state: AgentState) -> dict:
    """Fill article bodies via trafilatura + ThreadPool.

    Phase 8: `competitor` channel articles take the snippet-only fast
    path (no HTTP fetch) — saves N×timeout seconds and Sonnet only ever
    sees their snippets via tag-tier downgrade anyway.
    """
    articles = list(state.get("searched_articles") or [])
    if not articles:
        return {"fetched_articles": articles}

    from dataclasses import replace as _dc_replace

    settings = get_settings()
    workers = settings.search.fetch_workers

    to_fetch = [a for a in articles if a.channel != "competitor"]
    fast_path = [a for a in articles if a.channel == "competitor"]

    enriched = list(fetch_bodies_parallel(to_fetch, max_workers=workers)) if to_fetch else []
    fast_filled = [
        _dc_replace(
            a,
            body=a.snippet,
            body_source="snippet" if a.snippet else "empty",
        )
        for a in fast_path
    ]

    # Preserve original input order — articles came in mixed by channel.
    by_url = {a.url: a for a in enriched + fast_filled}
    final = [by_url.get(a.url, a) for a in articles]

    full = sum(1 for a in final if a.body_source == "full")
    snippet = sum(1 for a in final if a.body_source == "snippet")
    _LOGGER.info(
        "[fetch] total=%d full=%d snippet_fallback=%d (competitor fast-path=%d)",
        len(final), full, snippet, len(fast_filled),
    )
    return {"fetched_articles": final}


@_stage(STAGE_PREPROCESS)
def preprocess_node(state: AgentState) -> dict:
    """Translate → tag → dedup via local Exaone + bge-m3."""
    articles = list(state.get("fetched_articles") or [])
    if not articles:
        return {"processed_articles": articles}
    lang = state.get("lang")
    kept, meta = preprocess_articles(articles, target_lang=lang)
    _LOGGER.info(
        "[preprocess] in=%d translated=%d tagged=%d kept=%d",
        meta.get("n_input", 0),
        meta.get("n_translated", 0),
        meta.get("n_tagged", 0),
        meta.get("n_output", 0),
    )
    return {"processed_articles": kept}


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
        list(state.get("processed_articles") or []),
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
    articles = list(state.get("processed_articles") or [])
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
    failed_stage = state.get("failed_stage")
    status = "failed" if failed_stage else "completed"
    ended_at = time.perf_counter()

    out_raw = state.get("output_dir")
    if out_raw is None:
        _LOGGER.error("persist_node: output_dir missing from state; skipping persist")
        stages = list(state.get("stages_completed") or [])
        if STAGE_PERSIST not in stages:
            stages.append(STAGE_PERSIST)
        return {
            "stages_completed": stages,
            "status": status,
            "ended_at": ended_at,
            "current_stage": None,
        }
    output_dir = Path(out_raw)
    intermediate = output_dir / "intermediate"
    intermediate.mkdir(parents=True, exist_ok=True)

    # Always write what we have — even partial. The canonical
    # `articles_after_preprocess.json` holds the most advanced stage's
    # output (processed > fetched > searched). On failure we also dump
    # earlier-stage snapshots so post-mortem can see the progression.
    processed = state.get("processed_articles") or []
    fetched = state.get("fetched_articles") or []
    searched = state.get("searched_articles") or []
    latest = processed or fetched or searched
    if latest:
        _write_json(intermediate / "articles_after_preprocess.json", latest)
    if failed_stage:
        if searched and not processed:
            _write_json(intermediate / "articles_searched.json", searched)
        if fetched and not processed:
            _write_json(intermediate / "articles_fetched.json", fetched)

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
    duration_s = (ended_at - started) if started is not None else None
    summary = {
        "run_id": state.get("run_id"),
        "company": state.get("company"),
        "industry": state.get("industry"),
        "lang": state.get("lang"),
        "status": status,
        "duration_s": duration_s,
        "started_at": started,
        "ended_at": ended_at,
        "usage": state.get("usage") or {},
        "errors": state.get("errors") or [],
        "failed_stage": failed_stage,
        "current_stage": None if status == "completed" else failed_stage,
        "stages_completed": stages,
        "proposal_md_path": str(md_path) if md_path else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(intermediate / "run_summary.json", summary)

    return {
        "stages_completed": stages,
        "status": status,
        "ended_at": ended_at,
        "current_stage": None if status == "completed" else failed_stage,
    }


def route_after_stage(state: AgentState) -> str:
    """Conditional-edge router — 'persist' if any stage failed, else 'continue'."""
    return "persist" if state.get("failed_stage") else "continue"
