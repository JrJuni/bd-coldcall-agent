"""Phase 5 — LangGraph StateGraph compilation.

Wires the 7 node adapters into a linear pipeline with conditional "skip to
persist on failure" edges. Nodes themselves never raise — the `@_stage`
decorator in `nodes.py` catches exceptions and sets `failed_stage` in
state; `route_after_stage` reads that flag and sends the run straight to
`persist_node` so partial artifacts always land on disk.

No `RetryPolicy` for Phase 5. Transient network/LLM failures are rare on
single-target runs and `synthesize_proposal_points` already retries once
internally with a temperature bump. Phase 7 can add RetryPolicy when we
need resumable background runs.

The graph takes a checkpointer so `graph.invoke(..., config=
{"configurable": {"thread_id": run_id}})` stamps each step. Default is
`MemorySaver` for CLI / tests; the FastAPI backend (Phase 7) injects a
`SqliteSaver` so runs survive process restarts and can be resumed by
`run_id`.
"""
from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from src.graph import nodes as _nodes
from src.graph.state import AgentState


# Public stage names for test assertions / docs.
STAGES = (
    _nodes.STAGE_SEARCH,
    _nodes.STAGE_FETCH,
    _nodes.STAGE_PREPROCESS,
    _nodes.STAGE_RETRIEVE,
    _nodes.STAGE_SYNTHESIZE,
    _nodes.STAGE_DRAFT,
    _nodes.STAGE_PERSIST,
)


def build_graph(*, checkpointer: Any | None = None):
    """Compile the full 6-stage + persist pipeline.

    Returns a compiled LangGraph ready for `.invoke(state, config)`. The
    caller stamps a `thread_id` in the run config so the checkpointer can
    persist per-step state.
    """
    g = StateGraph(AgentState)

    # Register nodes (look up from the nodes module at build time so tests
    # can monkeypatch individual node functions before compilation).
    g.add_node(_nodes.STAGE_SEARCH, _nodes.search_node)
    g.add_node(_nodes.STAGE_FETCH, _nodes.fetch_node)
    g.add_node(_nodes.STAGE_PREPROCESS, _nodes.preprocess_node)
    g.add_node(_nodes.STAGE_RETRIEVE, _nodes.retrieve_node)
    g.add_node(_nodes.STAGE_SYNTHESIZE, _nodes.synthesize_node)
    g.add_node(_nodes.STAGE_DRAFT, _nodes.draft_node)
    g.add_node(_nodes.STAGE_PERSIST, _nodes.persist_node)

    g.add_edge(START, _nodes.STAGE_SEARCH)

    # Each stage 1–5 has a conditional edge: failed_stage → persist; else next.
    g.add_conditional_edges(
        _nodes.STAGE_SEARCH,
        _nodes.route_after_stage,
        {"continue": _nodes.STAGE_FETCH, "persist": _nodes.STAGE_PERSIST},
    )
    g.add_conditional_edges(
        _nodes.STAGE_FETCH,
        _nodes.route_after_stage,
        {"continue": _nodes.STAGE_PREPROCESS, "persist": _nodes.STAGE_PERSIST},
    )
    g.add_conditional_edges(
        _nodes.STAGE_PREPROCESS,
        _nodes.route_after_stage,
        {"continue": _nodes.STAGE_RETRIEVE, "persist": _nodes.STAGE_PERSIST},
    )
    g.add_conditional_edges(
        _nodes.STAGE_RETRIEVE,
        _nodes.route_after_stage,
        {"continue": _nodes.STAGE_SYNTHESIZE, "persist": _nodes.STAGE_PERSIST},
    )
    g.add_conditional_edges(
        _nodes.STAGE_SYNTHESIZE,
        _nodes.route_after_stage,
        {"continue": _nodes.STAGE_DRAFT, "persist": _nodes.STAGE_PERSIST},
    )
    # Draft → persist is unconditional (persist is the only downstream node).
    g.add_edge(_nodes.STAGE_DRAFT, _nodes.STAGE_PERSIST)
    g.add_edge(_nodes.STAGE_PERSIST, END)

    return g.compile(checkpointer=checkpointer or MemorySaver())
