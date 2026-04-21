"""Phase 7 — /healthz endpoint.

Reports whether lifespan warmup succeeded so a deployment probe can
distinguish "API process up, models still loading" from "API fully
ready." No dependency on downstream services — intentionally kept cheap.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from src.api.schemas import HealthResponse


router = APIRouter()


@router.get("/healthz", response_model=HealthResponse)
async def healthz(request: Request) -> HealthResponse:
    app_state = request.app.state
    return HealthResponse(
        status="ok",
        warmup_skipped=bool(getattr(app_state, "warmup_skipped", False)),
        exaone_loaded=bool(getattr(app_state, "exaone_loaded", False)),
        embedder_loaded=bool(getattr(app_state, "embedder_loaded", False)),
    )
