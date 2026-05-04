"""Phase 10 P10-8 — /dashboard aggregator.

One endpoint that pulls the slimmest snapshot needed for the Home page's
6-box dashboard. Each piece is best-effort — failures in a sub-aggregate
log a warning and surface as zeros instead of 500ing the whole page.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter

from src.api import store as _store
from src.api.schemas import (
    DashboardCostSummary,
    DashboardNewsMini,
    DashboardRagStatus,
    DashboardRecentDiscovery,
    DashboardRecentRun,
    DashboardResponse,
)
from src.config import loader as _config_loader
from src.rag.namespace import (
    DEFAULT_NAMESPACE,
    MANIFEST_FILENAME,
    list_namespaces,
    vectorstore_root_for,
)


_LOGGER = logging.getLogger(__name__)
router = APIRouter()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _recent_runs() -> list[DashboardRecentRun]:
    try:
        store = _store.get_run_store()
        records = list(reversed(store.list()))[:5]
        return [
            DashboardRecentRun(
                run_id=r.run_id,
                company=r.company,
                industry=r.industry,
                status=r.status,
                created_at=r.created_at,
            )
            for r in records
        ]
    except Exception as exc:
        _LOGGER.warning("dashboard: recent runs failed: %s", exc)
        return []


def _recent_discovery() -> DashboardRecentDiscovery | None:
    try:
        runs = _store.get_discovery_store().list_runs()
    except Exception as exc:
        _LOGGER.warning("dashboard: discovery list failed: %s", exc)
        return None
    if not runs:
        return None
    latest = runs[0]
    candidates = []
    try:
        candidates = _store.get_discovery_store().list_candidates(
            latest["run_id"]
        )
    except Exception as exc:
        _LOGGER.warning("dashboard: discovery candidates failed: %s", exc)
    tier_dist: dict[str, int] = {}
    for c in candidates:
        tier = c.get("tier") or "C"
        tier_dist[tier] = tier_dist.get(tier, 0) + 1
    return DashboardRecentDiscovery(
        run_id=latest["run_id"],
        namespace=latest.get("namespace") or DEFAULT_NAMESPACE,
        product=latest.get("product") or "",
        status=latest.get("status") or "queued",
        candidate_count=len(candidates),
        tier_distribution=tier_dist,
        generated_at=latest.get("generated_at") or latest.get("created_at") or "",
    )


def _pipeline_by_stage() -> dict[str, int]:
    try:
        rows = _store.get_target_store().list()
    except Exception as exc:
        _LOGGER.warning("dashboard: targets list failed: %s", exc)
        return {}
    out: dict[str, int] = {}
    for r in rows:
        stage = r.get("stage") or "planned"
        out[stage] = out.get(stage, 0) + 1
    return out


def _rag_status() -> list[DashboardRagStatus]:
    try:
        settings = _config_loader.get_settings()
        vs_root = Path(settings.rag.vectorstore_path)
        if not vs_root.is_absolute():
            vs_root = _config_loader.PROJECT_ROOT / vs_root
    except Exception as exc:
        _LOGGER.warning("dashboard: settings load failed: %s", exc)
        return []

    try:
        names = list_namespaces(vs_root)
    except Exception as exc:
        _LOGGER.warning("dashboard: list_namespaces failed: %s", exc)
        names = []
    if DEFAULT_NAMESPACE not in names:
        names.insert(0, DEFAULT_NAMESPACE)

    out: list[DashboardRagStatus] = []
    for name in names:
        manifest = vectorstore_root_for(vs_root, name) / MANIFEST_FILENAME
        if not manifest.exists():
            out.append(DashboardRagStatus(namespace=name, is_indexed=False))
            continue
        try:
            raw = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            out.append(DashboardRagStatus(namespace=name, is_indexed=False))
            continue
        documents = raw.get("documents") or {}
        chunk_total = sum(
            int(entry.get("chunk_count") or 0) for entry in documents.values()
        )
        out.append(
            DashboardRagStatus(
                namespace=name,
                document_count=len(documents),
                chunk_count=chunk_total,
                is_indexed=bool(documents),
            )
        )
    return out


def _news_mini() -> DashboardNewsMini | None:
    try:
        record = _store.get_news_store().latest_for_namespace(DEFAULT_NAMESPACE)
    except Exception as exc:
        _LOGGER.warning("dashboard: news latest failed: %s", exc)
        return None
    if record is None:
        return None
    titles = [
        a.get("title", "")
        for a in (record.get("articles") or [])[:3]
        if a.get("title")
    ]
    return DashboardNewsMini(
        namespace=record.get("namespace") or DEFAULT_NAMESPACE,
        generated_at=record.get("generated_at") or "",
        article_count=int(record.get("article_count") or 0),
        seed_query=record.get("seed_query"),
        top_titles=titles,
    )


def _interactions_count() -> int:
    try:
        return len(_store.get_interaction_store().list(limit=1000))
    except Exception as exc:
        _LOGGER.warning("dashboard: interactions count failed: %s", exc)
        return 0


def _cost_summary() -> DashboardCostSummary:
    """Phase 11+ — pull USD KPIs + budget status from the cost calculator.

    Same data source as `/cost/summary`, but only the fields the Home box
    needs. Failures fall through to a zero-state summary instead of 500ing.
    """
    try:
        from src.api.routes.cost import _gather_records
        from src.cost import calculator as _calc

        pricing = _config_loader.load_pricing()
        budget_cfg = _config_loader.load_cost_budget()
        records, _model = _gather_records()
        today = _calc.now_utc_date()
        kpi = _calc.kpi_block(records, pricing, today)
        budget_state = _calc.budget_state(records, pricing, budget_cfg, today)
        return DashboardCostSummary(
            this_month_usd=kpi["this_month_usd"],
            last_month_usd=kpi["last_month_usd"],
            cumulative_usd=kpi["cumulative_usd"],
            cache_savings_usd=kpi["cache_savings_usd"],
            cache_savings_pct=kpi["cache_savings_pct"],
            monthly_budget_usd=budget_state["monthly_usd"],
            used_pct=budget_state["used_pct"],
            breached=budget_state["breached"],
            over_budget=budget_state["over_budget"],
        )
    except Exception as exc:
        _LOGGER.warning("dashboard: cost summary failed: %s", exc)
        return DashboardCostSummary()


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard() -> DashboardResponse:
    return DashboardResponse(
        recent_runs=_recent_runs(),
        recent_discovery=_recent_discovery(),
        pipeline_by_stage=_pipeline_by_stage(),
        rag=_rag_status(),
        news=_news_mini(),
        interactions_count=_interactions_count(),
        cost=_cost_summary(),
        generated_at=_now_iso(),
    )
