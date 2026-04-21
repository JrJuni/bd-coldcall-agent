"""Phase 5 — thin orchestrator that seeds state and invokes the compiled graph.

CLI (Phase 6) and the FastAPI backend (Phase 7) both import and call
`run(...)` so a single place owns: run_id assignment, `output_dir`
convention (`outputs/{company}_{YYYYMMDD}`), `started_at` stamping, and
LangGraph invoke config. The function returns the final `AgentState` as
a plain dict so callers can introspect usage / errors / paths without
re-parsing the run_summary.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from src.config.loader import get_settings
from src.graph.pipeline import build_graph
from src.graph.state import AgentState, new_state


def run(
    *,
    company: str,
    industry: str,
    lang: Literal["en", "ko"] = "en",
    output_root: Path | None = None,
    top_k: int | None = None,
    run_id: str | None = None,
) -> AgentState:
    """Run the full 6-stage BD pipeline for one target.

    Args:
        company: Target company name used as the search + retrieve query.
        industry: Industry label threaded through to the Sonnet synthesis prompt.
        lang: Output language. "en" or "ko".
        output_root: Parent directory. A per-run subdirectory
            `{company}_{YYYYMMDD}/` is created under it. Defaults to
            `settings.output.dir`.
        top_k: Override for `settings.llm.claude_rag_top_k`.
        run_id: Explicit thread id for checkpointer. Auto-generated from
            `{YYYYMMDD-HHMMSS}-{company}` if omitted.

    Returns the final state dict (includes `proposal_md`, `usage`,
    `errors`, `failed_stage`, `stages_completed`, and `output_dir`).
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

    graph = build_graph()
    result = graph.invoke(
        state,
        config={"configurable": {"thread_id": run_id}},
    )
    return result
