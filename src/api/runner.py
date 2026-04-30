"""Phase 7 — background execution adapters for /runs and /ingest.

Both functions run synchronously inside FastAPI `BackgroundTasks`, which
dispatches sync callables through anyio's worker thread pool. Progress
is streamed back to callers by mutating shared `RunStore`/`IngestStore`
records — SSE readers then poll the per-record event log on the event
loop. No cross-thread queues or coroutine threadsafe plumbing, because
the event log + record snapshot pattern is enough at MVP scale (one
background run at a time per run_id).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.api.store import (
    DiscoveryStore,
    IngestStore,
    RunRecord,
    RunStore,
    get_discovery_store,
    get_ingest_store,
    get_run_store,
)

_LOGGER = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _article_counts(state: dict[str, Any]) -> dict[str, int]:
    return {
        "searched": len(state.get("searched_articles") or []),
        "fetched": len(state.get("fetched_articles") or []),
        "processed": len(state.get("processed_articles") or []),
    }


def execute_run(
    *,
    run_id: str,
    company: str,
    industry: str,
    lang: str,
    top_k: int | None,
    output_root: Path | None = None,
    checkpointer: Any | None = None,
    store: RunStore | None = None,
) -> None:
    """Drive the pipeline via `orchestrator.run_streaming` and mirror progress
    into the RunStore record so /runs/{id} and SSE can observe it.
    """
    from src.core import orchestrator as _orchestrator

    store = store or get_run_store()
    record = store.get(run_id)
    if record is None:
        _LOGGER.error("execute_run: run_id %s not found in store", run_id)
        return

    store.update(run_id, status="running", started_at=_now_iso())
    record.append_event("run_started", {"run_id": run_id, "company": company})

    final_state: dict[str, Any] | None = None
    prev_stages: set[str] = set()
    prev_stage: str | None = None

    try:
        for state in _orchestrator.run_streaming(
            company=company,
            industry=industry,
            lang=lang,  # type: ignore[arg-type]
            output_root=output_root,
            top_k=top_k,
            run_id=run_id,
            checkpointer=checkpointer,
        ):
            final_state = dict(state)
            stages = list(final_state.get("stages_completed") or [])
            current = final_state.get("current_stage")
            newly_done = [s for s in stages if s not in prev_stages]
            for s in newly_done:
                record.append_event("stage_completed", {"stage": s})
            if current != prev_stage and current:
                record.append_event("stage_started", {"stage": current})
            prev_stages = set(stages)
            prev_stage = current

            store.update(
                run_id,
                status=final_state.get("status") or "running",
                current_stage=current,
                stages_completed=stages,
                failed_stage=final_state.get("failed_stage"),
                usage=dict(final_state.get("usage") or {}),
                errors=list(final_state.get("errors") or []),
                article_counts=_article_counts(final_state),
                proposal_points_count=len(final_state.get("proposal_points") or []),
            )

        if final_state is not None:
            started = final_state.get("started_at")
            ended = final_state.get("ended_at")
            duration = (
                round(float(ended) - float(started), 3)
                if started is not None and ended is not None
                else None
            )
            status = final_state.get("status") or (
                "failed" if final_state.get("failed_stage") else "completed"
            )
            output_dir = final_state.get("output_dir")
            store.update(
                run_id,
                status=status,
                proposal_md=final_state.get("proposal_md") or None,
                output_dir=str(output_dir) if output_dir else None,
                ended_at=_now_iso(),
                duration_s=duration,
            )
            record.append_event(
                "run_completed" if status == "completed" else "run_failed",
                {
                    "status": status,
                    "failed_stage": final_state.get("failed_stage"),
                    "duration_s": duration,
                    "proposal_points_count": len(final_state.get("proposal_points") or []),
                },
            )
    except Exception as exc:
        _LOGGER.exception("execute_run: unhandled exception in pipeline")
        err = {
            "stage": "runner",
            "error_type": type(exc).__name__,
            "message": str(exc),
        }
        store.update(
            run_id,
            status="failed",
            failed_stage="runner",
            ended_at=_now_iso(),
            errors=list(record.errors) + [err],
        )
        record.append_event("run_failed", err)


def execute_discovery_run(
    *,
    run_id: str,
    namespace: str,
    region: str,
    product: str,
    seed_summary: str | None,
    seed_query: str | None,
    top_k: int | None,
    n_industries: int,
    n_per_industry: int,
    lang: str,
    include_sector_leaders: bool,
    store: DiscoveryStore | None = None,
) -> None:
    """Drive `discover_targets()` and persist the result into SQLite.

    `discover_targets` is heavy (Sonnet 1 call + RAG retrieve), so this
    runs in the BackgroundTasks worker. Progress is mirrored into the
    DiscoveryStore event log for SSE consumers, and the final
    DiscoveryResult.candidates list is bulk-inserted into the
    `discovery_candidates` table after parsing.

    Module-level imports of `src.core.discover` and `src.core.scoring`
    are intentionally module-attr only (`_discover.discover_targets`,
    `_scoring.load_weights`) so tests can monkeypatch them — the
    `from src.core import discover as _discover` form keeps the binding
    on the module object, not on this module's namespace.
    """
    from src.core import discover as _discover

    store = store or get_discovery_store()
    record = store.get_run(run_id)
    if record is None:
        _LOGGER.error("execute_discovery_run: run_id %s not found", run_id)
        return

    store.update_run(run_id, status="running", started_at=_now_iso())
    store.append_event(
        run_id,
        "run_started",
        {
            "run_id": run_id,
            "namespace": namespace,
            "product": product,
            "region": region,
        },
    )

    try:
        kwargs: dict[str, Any] = dict(
            lang=lang,
            n_industries=n_industries,
            n_per_industry=n_per_industry,
            seed_summary=seed_summary,
            product=product,
            region=region,
            namespace=namespace,
            include_sector_leaders=include_sector_leaders,
            write_artifacts=False,
        )
        if seed_query:
            kwargs["seed_query"] = seed_query
        if top_k is not None:
            kwargs["top_k"] = top_k

        result = _discover.discover_targets(**kwargs)

        candidates_payload = [
            {
                "name": c.name,
                "industry": c.industry,
                "scores": dict(c.scores),
                "final_score": float(c.final_score),
                "tier": c.tier,
                "rationale": c.rationale,
                "status": "active",
            }
            for c in result.candidates
        ]
        store.insert_candidates(run_id, candidates_payload)

        store.update_run(
            run_id,
            seed_doc_count=result.seed_doc_count,
            seed_chunk_count=result.seed_chunk_count,
            seed_summary=result.seed_summary or seed_summary,
            generated_at=result.generated_at.isoformat(),
            usage=dict(result.usage or {}),
            status="completed",
            ended_at=_now_iso(),
        )

        tier_dist: dict[str, int] = {}
        for c in result.candidates:
            tier_dist[c.tier] = tier_dist.get(c.tier, 0) + 1

        store.append_event(
            run_id,
            "run_completed",
            {
                "candidate_count": len(result.candidates),
                "tier_distribution": tier_dist,
                "usage": dict(result.usage or {}),
            },
        )
    except Exception as exc:
        _LOGGER.exception("execute_discovery_run: discover_targets failed")
        message = f"{type(exc).__name__}: {exc}"
        store.update_run(
            run_id,
            status="failed",
            failed_stage="discover_targets",
            error_message=message,
            ended_at=_now_iso(),
        )
        store.append_event(
            run_id,
            "run_failed",
            {"error_type": type(exc).__name__, "message": str(exc)},
        )


def execute_discovery_recompute(
    *,
    run_id: str,
    weights_override: dict[str, float] | None = None,
    product: str | None = None,
    store: DiscoveryStore | None = None,
) -> dict[str, Any]:
    """Re-score every candidate in `run_id` with new weights.

    No LLM call — this is the deterministic part of the discovery
    pipeline (Phase 9.1). Returns the applied weights + tier distribution
    so the caller can echo back to the UI.

    Resolution order for the weight vector:
      1. `weights_override` (UI slider state) — used as-is, normalized
         only if its sum drifts from 1.0.
      2. `product` key (if no override) → `load_weights(product)` from
         `config/weights.yaml::products.<name>`.
      3. The run's stored `product` field (fallback) → same lookup.
    """
    from src.core import scoring as _scoring

    store = store or get_discovery_store()
    run = store.get_run(run_id)
    if run is None:
        raise KeyError(f"run_id {run_id!r} not found")

    if weights_override is not None:
        weights = _normalize_weights(weights_override)
    else:
        product_key = product if product is not None else run.get("product") or None
        weights = _scoring.load_weights(product_key)

    rules = _scoring.load_tier_rules()
    candidates = store.list_candidates(run_id)

    updates: list[tuple[int, float, str]] = []
    tier_dist: dict[str, int] = {}
    for c in candidates:
        try:
            score = _scoring.calc_final_score(c["scores"], weights)
        except ValueError as exc:
            _LOGGER.warning(
                "recompute: candidate %s skipped (%s)", c["id"], exc
            )
            continue
        tier = _scoring.decide_tier(score, rules)
        updates.append((c["id"], round(score, 3), tier))
        tier_dist[tier] = tier_dist.get(tier, 0) + 1

    store.bulk_update_tiers(updates)
    refreshed = store.list_candidates(run_id)
    return {
        "candidates": refreshed,
        "weights_applied": weights,
        "tier_distribution": tier_dist,
    }


def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    total = sum(float(v) for v in weights.values())
    if total <= 0:
        raise ValueError("weight sum must be positive")
    if abs(total - 1.0) <= 1e-3:
        return {k: float(v) for k, v in weights.items()}
    return {k: float(v) / total for k, v in weights.items()}


def execute_ingest(
    *,
    task_id: str,
    params: dict[str, Any],
    store: IngestStore | None = None,
) -> None:
    """Invoke `src.rag.indexer.main` with argv derived from `params`.

    The indexer returns an int exit code; non-zero marks the task
    failed. Exceptions are caught and written to the task record so the
    endpoint always reports a definitive status.
    """
    from src.rag import indexer as _indexer

    store = store or get_ingest_store()
    task = store.get(task_id)
    if task is None:
        _LOGGER.error("execute_ingest: task_id %s not found", task_id)
        return

    store.update(task_id, status="running")

    argv: list[str] = []
    if params.get("notion"):
        argv.append("--notion")
    if params.get("force"):
        argv.append("--force")
    if params.get("dry_run"):
        argv.append("--dry-run")

    try:
        code = _indexer.main(argv)
    except Exception as exc:
        _LOGGER.exception("execute_ingest: indexer raised")
        store.update(
            task_id,
            status="failed",
            ended_at=_now_iso(),
            message=f"{type(exc).__name__}: {exc}",
        )
        return

    if code == 0:
        store.update(
            task_id,
            status="completed",
            ended_at=_now_iso(),
            message="Ingest finished",
        )
    else:
        store.update(
            task_id,
            status="failed",
            ended_at=_now_iso(),
            message=f"Indexer exited with code {code}",
        )
