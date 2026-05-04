"""Cost Explorer — `/cost/summary` aggregator and active-model swap.

Pulls run records from three sources (RunStore, DiscoveryStore SQLite,
rag_summaries SQLite), normalizes them into a single record shape, and
delegates aggregation to ``src.cost.calculator``.

`POST /cost/active-model` flips `llm.claude_model` in `config/settings.yaml`
in-place (line-targeted regex substitution to preserve comments) so users
can swap Sonnet ↔ Haiku from the UI without hand-editing yaml.

Module-attr access only (``from src.api import store as _store``,
``from src.config import loader as _config_loader``) per the project's
DO-NOT rule, so tests can monkeypatch.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.api import db as _db
from src.api import store as _store
from src.api.config import get_api_settings
from src.api.schemas import (
    CostBreakdownItem,
    CostBudgetState,
    CostDailyPoint,
    CostKpi,
    CostPerUnit,
    CostRecentRun,
    CostRecentRunTokens,
    CostSummaryResponse,
)
from src.config import loader as _config_loader
from src.cost import calculator as _calc


_LOGGER = logging.getLogger(__name__)
router = APIRouter()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _rag_summary_records(fallback_model: str) -> list[dict[str, Any]]:
    """Pull every cached `rag_summaries` row as a Cost Explorer record."""
    try:
        db_path = Path(get_api_settings().app_db)
    except Exception as exc:
        _LOGGER.warning("cost: rag db path resolve failed: %s", exc)
        return []

    out: list[dict[str, Any]] = []
    try:
        with _db.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT ws_slug, namespace, path, model, usage_json, generated_at"
                " FROM rag_summaries"
            ).fetchall()
    except Exception as exc:
        _LOGGER.warning("cost: rag_summaries query failed: %s", exc)
        return []

    for row in rows:
        try:
            usage = json.loads(row["usage_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            usage = {}
        path_part = f":{row['path']}" if row["path"] else ""
        out.append(
            {
                "run_id": (
                    f"rag:{row['ws_slug']}:{row['namespace']}{path_part}"
                ),
                "created_at": row["generated_at"] or "",
                "run_type": "rag_summary",
                "model": row["model"] or fallback_model,
                "usage": usage if isinstance(usage, dict) else {},
                "label": (
                    f"{row['ws_slug']}/{row['namespace']}{path_part}"
                ),
                "status": "completed",
            }
        )
    return out


def _gather_records() -> tuple[list[dict[str, Any]], str]:
    """Return (records, fallback_model). Records carry their own `model`
    when stored, falling back to the active settings value otherwise."""
    try:
        fallback_model = _config_loader.get_settings().llm.claude_model
    except Exception:
        fallback_model = "claude-sonnet-4-6"

    records: list[dict[str, Any]] = []

    try:
        for rec in _store.get_run_store().list():
            usage = getattr(rec, "usage", {}) or {}
            records.append(
                {
                    "run_id": rec.run_id,
                    "created_at": rec.created_at,
                    "run_type": "proposal",
                    "model": getattr(rec, "claude_model", None) or fallback_model,
                    "usage": usage,
                    "label": f"{rec.company} · {rec.industry}",
                    "status": rec.status,
                }
            )
    except Exception as exc:
        _LOGGER.warning("cost: proposal records failed: %s", exc)

    try:
        for run in _store.get_discovery_store().list_runs():
            usage = run.get("usage") if isinstance(run, dict) else {}
            records.append(
                {
                    "run_id": run.get("run_id", ""),
                    "created_at": (
                        run.get("created_at") or run.get("generated_at") or ""
                    ),
                    "run_type": "discovery",
                    "model": run.get("claude_model") or fallback_model,
                    "usage": usage or {},
                    "label": (
                        f"{run.get('namespace') or 'default'} · "
                        f"{run.get('product') or ''}"
                    ),
                    "status": run.get("status") or "queued",
                    "candidate_count": int(run.get("candidate_count") or 0),
                }
            )
    except Exception as exc:
        _LOGGER.warning("cost: discovery records failed: %s", exc)

    records.extend(_rag_summary_records(fallback_model))

    return records, fallback_model


# ── Active model selection ──────────────────────────────────────────────


class AvailableModel(BaseModel):
    id: str
    input_per_mtok: float
    output_per_mtok: float
    cache_read_per_mtok: float
    cache_write_per_mtok: float


class ActiveModelView(BaseModel):
    active: str | None
    available: list[AvailableModel] = Field(default_factory=list)


class ActiveModelSwap(BaseModel):
    model: str = Field(..., min_length=1, max_length=200)


def _available_models() -> list[AvailableModel]:
    pricing = _config_loader.load_pricing()
    out: list[AvailableModel] = []
    for model_id, rates in pricing.llm.items():
        out.append(
            AvailableModel(
                id=model_id,
                input_per_mtok=rates.input_per_mtok,
                output_per_mtok=rates.output_per_mtok,
                cache_read_per_mtok=rates.cache_read_per_mtok,
                cache_write_per_mtok=rates.cache_write_per_mtok,
            )
        )
    out.sort(key=lambda m: m.id)
    return out


@router.get("/cost/active-model", response_model=ActiveModelView)
async def get_active_model() -> ActiveModelView:
    try:
        active = _config_loader.get_settings().llm.claude_model
    except Exception:
        active = None
    return ActiveModelView(active=active, available=_available_models())


_CLAUDE_MODEL_LINE_RE = re.compile(
    r"^(?P<indent>\s*)claude_model:\s*[^\n#]*(?P<trail>\s*(?:#.*)?)$",
    re.MULTILINE,
)


def _swap_claude_model_line(raw_yaml: str, new_model: str) -> str:
    """Replace the `claude_model:` value in-place, preserving indentation
    and any trailing comment. Falls back to a yaml round-trip when no
    matching line is found (e.g. user wrote a flow-style mapping)."""
    if _CLAUDE_MODEL_LINE_RE.search(raw_yaml):
        return _CLAUDE_MODEL_LINE_RE.sub(
            lambda m: f"{m.group('indent')}claude_model: {new_model}{m.group('trail')}",
            raw_yaml,
            count=1,
        )
    # Fallback — parse, mutate, dump. Loses comments but keeps semantics.
    data = yaml.safe_load(raw_yaml) or {}
    if not isinstance(data, dict):
        raise ValueError("settings.yaml top-level is not a mapping")
    llm = data.setdefault("llm", {})
    if not isinstance(llm, dict):
        raise ValueError("settings.yaml `llm` is not a mapping")
    llm["claude_model"] = new_model
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


@router.post("/cost/active-model", response_model=ActiveModelView)
async def post_active_model(payload: ActiveModelSwap) -> ActiveModelView:
    target = payload.model.strip()
    if not target:
        raise HTTPException(status_code=422, detail="model must be non-empty")

    available_ids = {m.id for m in _available_models()}
    if target not in available_ids:
        raise HTTPException(
            status_code=422,
            detail=(
                f"model {target!r} is not in pricing.yaml; "
                f"available: {sorted(available_ids)}"
            ),
        )

    cfg_path = Path(_config_loader.CONFIG_DIR) / "settings.yaml"
    if not cfg_path.exists():
        raise HTTPException(
            status_code=404, detail=f"{cfg_path} not found"
        )
    raw = cfg_path.read_text(encoding="utf-8")
    try:
        new_raw = _swap_claude_model_line(raw, target)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Validate the post-swap yaml passes the existing 2-pass schema check
    # before atomic-write — same guarantee Settings PUT gives.
    from src.config.schemas import Settings

    try:
        parsed = yaml.safe_load(new_raw) or {}
        Settings(**parsed)
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail=f"validation failed after swap: {exc}"
        ) from exc

    tmp = cfg_path.with_suffix(cfg_path.suffix + ".tmp")
    tmp.write_text(new_raw, encoding="utf-8")
    tmp.replace(cfg_path)

    try:
        _config_loader.get_settings.cache_clear()
    except AttributeError:
        pass

    return ActiveModelView(active=target, available=_available_models())


# ── Cost summary ────────────────────────────────────────────────────────


@router.get("/cost/summary", response_model=CostSummaryResponse)
async def get_cost_summary(
    days: int = Query(30, ge=1, le=365),
) -> CostSummaryResponse:
    pricing = _config_loader.load_pricing()
    budget = _config_loader.load_cost_budget()
    records, _ = _gather_records()
    today = _calc.now_utc_date()

    kpi = _calc.kpi_block(records, pricing, today)
    daily = _calc.aggregate_daily(records, pricing, days=days, today=today)
    by_model = _calc.aggregate_by(records, pricing, dim="model")
    by_run_type = _calc.aggregate_by(records, pricing, dim="run_type")
    per_unit = _calc.per_unit(records, pricing)
    budget_state = _calc.budget_state(records, pricing, budget, today)
    recent = _calc.recent_runs_with_usd(records, pricing, limit=20)

    return CostSummaryResponse(
        kpi=CostKpi(**kpi),
        daily_series=[CostDailyPoint(**p) for p in daily],
        by_model=[CostBreakdownItem(**i) for i in by_model],
        by_run_type=[CostBreakdownItem(**i) for i in by_run_type],
        per_unit=CostPerUnit(**per_unit),
        budget=CostBudgetState(**budget_state),
        recent_runs=[
            CostRecentRun(
                run_id=r["run_id"],
                created_at=r["created_at"],
                run_type=r["run_type"],
                model=r["model"],
                label=r["label"],
                tokens=CostRecentRunTokens(**r["tokens"]),
                usd=r["usd"],
            )
            for r in recent
        ],
        days=days,
        generated_at=_now_iso(),
    )
