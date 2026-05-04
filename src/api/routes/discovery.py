"""Phase 10 P10-2b — /discovery endpoints.

Discovery is a single-Sonnet-call pipeline (cf. `src/core/discover.py`),
so the runner mirrors `runs.py` but with a flatter event log:
  queued → running → completed / failed

The recompute endpoint is the LLM-free side of Phase 9.1 — UI slider
state arrives as a 6-dim weight dict, and `execute_discovery_recompute`
re-runs `calc_final_score` + `decide_tier` only, returning the new
candidate list synchronously (no background task, no SSE).
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from src.api import runner as _runner
from src.api import store as _store
from src.config import loader as _config_loader
from src.api.schemas import (
    DiscoveryCandidate,
    DiscoveryCandidateUpdate,
    DiscoveryPromoteResponse,
    DiscoveryRecomputeRequest,
    DiscoveryRecomputeResponse,
    DiscoveryRunCreate,
    DiscoveryRunDetail,
    DiscoveryRunListResponse,
    DiscoveryRunSummary,
)


_LOGGER = logging.getLogger(__name__)
SSE_POLL_INTERVAL_S = 0.15


router = APIRouter()


def _make_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"discover-{stamp}-{uuid.uuid4().hex[:6]}"


def _attach_distribution(run_dict: dict) -> dict:
    """Ensure the run dict has candidate_count + tier_distribution keys.

    `DiscoveryStore.list_runs` populates these from a single query;
    `get_run` does not, so this helper backfills via a candidate scan.
    """
    if "candidate_count" not in run_dict or "tier_distribution" not in run_dict:
        store = _store.get_discovery_store()
        cands = store.list_candidates(run_dict["run_id"])
        run_dict["candidate_count"] = len(cands)
        dist: dict[str, int] = {}
        for c in cands:
            dist[c["tier"]] = dist.get(c["tier"], 0) + 1
        run_dict["tier_distribution"] = dist
    return run_dict


# ── Runs ───────────────────────────────────────────────────────────────


@router.post("/discovery/runs", response_model=DiscoveryRunSummary, status_code=202)
async def create_discovery_run(
    payload: DiscoveryRunCreate,
    background_tasks: BackgroundTasks,
) -> DiscoveryRunSummary:
    store = _store.get_discovery_store()
    run_id = _make_run_id()
    try:
        active_model = _config_loader.get_settings().llm.claude_model
    except Exception:
        active_model = None
    record = store.create_run(
        run_id=run_id,
        generated_at=datetime.now(timezone.utc).isoformat(),
        namespace=payload.namespace,
        product=payload.product,
        region=payload.region,
        lang=payload.lang,
        seed_summary=payload.seed_summary,
        claude_model=active_model,
    )
    store.append_event(run_id, "run_queued", {"run_id": run_id})

    background_tasks.add_task(
        _runner.execute_discovery_run,
        run_id=run_id,
        namespace=payload.namespace,
        region=payload.region,
        product=payload.product,
        seed_summary=payload.seed_summary,
        seed_query=payload.seed_query,
        top_k=payload.top_k,
        n_industries=payload.n_industries,
        n_per_industry=payload.n_per_industry,
        lang=payload.lang,
        include_sector_leaders=payload.include_sector_leaders,
    )

    return DiscoveryRunSummary(**_attach_distribution(record))


@router.get("/discovery/runs", response_model=DiscoveryRunListResponse)
async def list_discovery_runs() -> DiscoveryRunListResponse:
    store = _store.get_discovery_store()
    runs = [DiscoveryRunSummary(**r) for r in store.list_runs()]
    return DiscoveryRunListResponse(runs=runs)


@router.get("/discovery/runs/{run_id}", response_model=DiscoveryRunDetail)
async def get_discovery_run(run_id: str) -> DiscoveryRunDetail:
    store = _store.get_discovery_store()
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")
    cands = store.list_candidates(run_id)
    run = _attach_distribution(run)
    return DiscoveryRunDetail(
        **run,
        candidates=[DiscoveryCandidate(**c) for c in cands],
    )


@router.delete("/discovery/runs/{run_id}", status_code=204)
async def delete_discovery_run(run_id: str) -> None:
    store = _store.get_discovery_store()
    if not store.delete_run(run_id):
        raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")
    return None


@router.get("/discovery/runs/{run_id}/events")
async def discovery_run_events(run_id: str, request: Request):
    store = _store.get_discovery_store()
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")

    async def generator() -> AsyncIterator[dict]:
        last_seq = 0
        while True:
            if await request.is_disconnected():
                return
            events = store.snapshot_events(run_id, since_seq=last_seq)
            for ev in events:
                last_seq = ev.seq
                yield {
                    "event": ev.kind,
                    "id": str(ev.seq),
                    "data": json.dumps(
                        {
                            "seq": ev.seq,
                            "ts": ev.ts,
                            "kind": ev.kind,
                            "payload": ev.payload,
                        },
                        ensure_ascii=False,
                    ),
                }
            run_now = store.get_run(run_id)
            if (
                run_now
                and run_now["status"] in ("completed", "failed")
                and not store.snapshot_events(run_id, since_seq=last_seq)
            ):
                return
            await asyncio.sleep(SSE_POLL_INTERVAL_S)

    return EventSourceResponse(generator())


# ── Candidates ─────────────────────────────────────────────────────────


@router.patch(
    "/discovery/candidates/{candidate_id}",
    response_model=DiscoveryCandidate,
)
async def patch_candidate(
    candidate_id: int, payload: DiscoveryCandidateUpdate
) -> DiscoveryCandidate:
    store = _store.get_discovery_store()
    row = store.update_candidate(
        candidate_id,
        name=payload.name,
        industry=payload.industry,
        scores=payload.scores,
        rationale=payload.rationale,
        status=payload.status,
        tier=payload.tier,
    )
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"candidate {candidate_id} not found"
        )
    return DiscoveryCandidate(**row)


@router.delete("/discovery/candidates/{candidate_id}", status_code=204)
async def delete_candidate(candidate_id: int) -> None:
    store = _store.get_discovery_store()
    if not store.delete_candidate(candidate_id):
        raise HTTPException(
            status_code=404, detail=f"candidate {candidate_id} not found"
        )
    return None


@router.post(
    "/discovery/candidates/{candidate_id}/promote",
    response_model=DiscoveryPromoteResponse,
)
async def promote_candidate(candidate_id: int) -> DiscoveryPromoteResponse:
    discovery = _store.get_discovery_store()
    cand = discovery.get_candidate(candidate_id)
    if cand is None:
        raise HTTPException(
            status_code=404, detail=f"candidate {candidate_id} not found"
        )
    targets = _store.get_target_store()
    notes_parts = []
    if cand.get("rationale"):
        notes_parts.append(cand["rationale"])
    notes_parts.append(
        f"Promoted from discovery candidate #{candidate_id} "
        f"(tier {cand['tier']}, score {cand['final_score']:.2f})"
    )
    target = targets.create(
        name=cand["name"],
        industry=cand["industry"],
        notes="\n".join(notes_parts),
        stage="planned",
        created_from="discovery_promote",
        discovery_candidate_id=candidate_id,
    )
    discovery.update_candidate(candidate_id, status="promoted")
    return DiscoveryPromoteResponse(
        candidate_id=candidate_id,
        target_id=int(target["id"]),
        candidate_status="promoted",
    )


# ── Recompute (LLM-free) ───────────────────────────────────────────────


@router.post(
    "/discovery/runs/{run_id}/recompute",
    response_model=DiscoveryRecomputeResponse,
)
async def recompute_discovery(
    run_id: str, payload: DiscoveryRecomputeRequest
) -> DiscoveryRecomputeResponse:
    try:
        result = _runner.execute_discovery_recompute(
            run_id=run_id,
            weights_override=payload.weights,
            product=payload.product,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return DiscoveryRecomputeResponse(
        run_id=run_id,
        candidates=[DiscoveryCandidate(**c) for c in result["candidates"]],
        weights_applied=result["weights_applied"],
        tier_distribution=result["tier_distribution"],
    )
