"""Phase 5/7 — thin orchestrator that seeds state and invokes the compiled graph.

CLI (Phase 6) and the FastAPI backend (Phase 7) both import and call
`run(...)` / `run_streaming(...)` so a single place owns: run_id assignment,
`output_dir` convention (`outputs/{company}_{YYYYMMDD}`), `started_at`
stamping, and LangGraph invoke config. `run_streaming` yields the state
after each super-step so the API layer can broadcast SSE progress without
re-implementing graph construction.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Literal

from src.config.loader import get_settings
from src.graph import pipeline as _pipeline
from src.graph.state import AgentState, new_state


def _prepare_run(
    *,
    company: str,
    industry: str,
    lang: Literal["en", "ko"],
    output_root: Path | None,
    top_k: int | None,
    run_id: str | None,
    checkpointer: Any | None,
) -> tuple[AgentState, Any, dict]:
    """Shared seed state / graph / invoke-config assembly.

    Returns `(state, compiled_graph, config)` so both `run` and
    `run_streaming` can dispatch identically without duplicating id /
    path / checkpointer plumbing.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y%m%d")
    if run_id is None:
        stamp = now.strftime("%Y%m%d-%H%M%S")
        run_id = f"{stamp}-{company}"

    root = Path(output_root or settings.output.dir)
    output_dir = root / f"{company}_{today}"

    state = new_state(
        company=company,
        industry=industry,
        lang=lang,
        output_dir=output_dir,
        run_id=run_id,
        top_k=top_k,
        started_at=time.perf_counter(),
    )
    graph = _pipeline.build_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": run_id}}
    return state, graph, config


def run(
    *,
    company: str,
    industry: str,
    lang: Literal["en", "ko"] = "en",
    output_root: Path | None = None,
    top_k: int | None = None,
    run_id: str | None = None,
    checkpointer: Any | None = None,
) -> AgentState:
    """Run the full 6-stage BD pipeline for one target.

    Returns the final state dict (includes `proposal_md`, `usage`,
    `errors`, `failed_stage`, `stages_completed`, and `output_dir`).
    """
    state, graph, config = _prepare_run(
        company=company,
        industry=industry,
        lang=lang,
        output_root=output_root,
        top_k=top_k,
        run_id=run_id,
        checkpointer=checkpointer,
    )
    return graph.invoke(state, config=config)


def run_streaming(
    *,
    company: str,
    industry: str,
    lang: Literal["en", "ko"] = "en",
    output_root: Path | None = None,
    top_k: int | None = None,
    run_id: str | None = None,
    checkpointer: Any | None = None,
) -> Iterator[AgentState]:
    """Yield each super-step state as the graph progresses.

    Useful for the FastAPI SSE endpoint — the caller can inspect
    `current_stage` / `stages_completed` / `status` on every yield and
    broadcast a structured event. The final yielded value is equivalent
    to `run(...)`'s return.
    """
    state, graph, config = _prepare_run(
        company=company,
        industry=industry,
        lang=lang,
        output_root=output_root,
        top_k=top_k,
        run_id=run_id,
        checkpointer=checkpointer,
    )
    for value in graph.stream(state, config=config, stream_mode="values"):
        yield value
