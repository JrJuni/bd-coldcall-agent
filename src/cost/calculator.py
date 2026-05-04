"""Cost Explorer — pure aggregation helpers.

Operates on a normalized record shape produced by the API route layer:

    {
        "run_id":     str,
        "created_at": str (ISO 8601),
        "run_type":   "proposal" | "discovery",
        "model":      str,
        "usage":      {input_tokens, output_tokens,
                       cache_read_input_tokens, cache_creation_input_tokens},
        "label":      str,                  # display only
        "status":     str,                  # for per-unit denominators
        "candidate_count": int (optional),  # discovery only
    }

Intentionally LLM/IO-free so the same code can be unit-tested with
hand-built fixtures.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from src.config.schemas import CostBudget, ModelRates, Pricing


_USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


def _rate_for(pricing: Pricing, model: str) -> ModelRates:
    """Return rates for ``model``; unknown model → zero-rate ModelRates."""
    rate = pricing.llm.get(model)
    if rate is not None:
        return rate
    # Fallback: prefix match (e.g. "claude-sonnet-4-6-20260101" → "claude-sonnet-4-6")
    for key, value in pricing.llm.items():
        if model.startswith(key):
            return value
    return ModelRates()


def usd_for_run(
    usage: dict[str, Any], model: str, pricing: Pricing
) -> dict[str, float]:
    """Compute USD breakdown for one run's usage dict."""
    rate = _rate_for(pricing, model)
    in_t = int(usage.get("input_tokens") or 0)
    out_t = int(usage.get("output_tokens") or 0)
    cr_t = int(usage.get("cache_read_input_tokens") or 0)
    cw_t = int(usage.get("cache_creation_input_tokens") or 0)
    in_usd = in_t * rate.input_per_mtok / 1_000_000
    out_usd = out_t * rate.output_per_mtok / 1_000_000
    cr_usd = cr_t * rate.cache_read_per_mtok / 1_000_000
    cw_usd = cw_t * rate.cache_write_per_mtok / 1_000_000
    total = in_usd + out_usd + cr_usd + cw_usd
    # Savings vs. full input price on the cache-read tokens.
    savings = cr_t * (rate.input_per_mtok - rate.cache_read_per_mtok) / 1_000_000
    return {
        "input_usd": in_usd,
        "output_usd": out_usd,
        "cache_read_usd": cr_usd,
        "cache_write_usd": cw_usd,
        "total_usd": total,
        "cache_savings_usd": savings,
    }


def _parse_iso_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").date()
        except ValueError:
            return None


def _is_same_month(d: date, ref: date) -> bool:
    return d.year == ref.year and d.month == ref.month


def _is_previous_month(d: date, ref: date) -> bool:
    if ref.month == 1:
        return d.year == ref.year - 1 and d.month == 12
    return d.year == ref.year and d.month == ref.month - 1


def kpi_block(
    records: Iterable[dict[str, Any]],
    pricing: Pricing,
    today: date,
) -> dict[str, float]:
    this_month = 0.0
    last_month = 0.0
    cumulative = 0.0
    cache_savings = 0.0
    for r in records:
        usd = usd_for_run(r.get("usage") or {}, r.get("model") or "", pricing)
        total = usd["total_usd"]
        cumulative += total
        cache_savings += usd["cache_savings_usd"]
        d = _parse_iso_date(r.get("created_at") or "")
        if d is None:
            continue
        if _is_same_month(d, today):
            this_month += total
        elif _is_previous_month(d, today):
            last_month += total
    counterfactual = cumulative + cache_savings
    pct = (cache_savings / counterfactual) if counterfactual > 0 else 0.0
    return {
        "this_month_usd": this_month,
        "last_month_usd": last_month,
        "cumulative_usd": cumulative,
        "cache_savings_usd": cache_savings,
        "cache_savings_pct": pct,
    }


def aggregate_daily(
    records: Iterable[dict[str, Any]],
    pricing: Pricing,
    *,
    days: int,
    today: date,
) -> list[dict[str, Any]]:
    """Bucket records by ISO date for the trailing ``days`` window.

    Returns a contiguous series — every day in the window appears, even
    those with $0, so the line chart doesn't get gaps.
    """
    cutoff = today - timedelta(days=days - 1)
    buckets: dict[date, float] = defaultdict(float)
    for r in records:
        d = _parse_iso_date(r.get("created_at") or "")
        if d is None or d < cutoff or d > today:
            continue
        usd = usd_for_run(r.get("usage") or {}, r.get("model") or "", pricing)
        buckets[d] += usd["total_usd"]
    series = []
    for i in range(days):
        d = cutoff + timedelta(days=i)
        series.append({"date": d.isoformat(), "usd": round(buckets.get(d, 0.0), 6)})
    return series


def aggregate_by(
    records: Iterable[dict[str, Any]],
    pricing: Pricing,
    *,
    dim: str,
) -> list[dict[str, Any]]:
    """Group records by ``dim`` ("model" or "run_type")."""
    if dim not in ("model", "run_type"):
        raise ValueError(f"dim must be 'model' or 'run_type', got {dim!r}")
    usd_buckets: dict[str, float] = defaultdict(float)
    token_buckets: dict[str, int] = defaultdict(int)
    for r in records:
        key = r.get(dim) or "unknown"
        usage = r.get("usage") or {}
        usd = usd_for_run(usage, r.get("model") or "", pricing)
        usd_buckets[key] += usd["total_usd"]
        token_buckets[key] += sum(int(usage.get(k) or 0) for k in _USAGE_KEYS)
    out = [
        {"label": k, "usd": round(usd_buckets[k], 6), "tokens": token_buckets[k]}
        for k in sorted(usd_buckets, key=lambda k: usd_buckets[k], reverse=True)
    ]
    return out


def per_unit(
    records: Iterable[dict[str, Any]], pricing: Pricing
) -> dict[str, float | None]:
    """USD per produced unit — proposal run, discovery candidate."""
    proposal_usd = 0.0
    proposal_count = 0
    discovery_usd = 0.0
    discovery_targets = 0
    for r in records:
        usd = usd_for_run(r.get("usage") or {}, r.get("model") or "", pricing)
        if r.get("run_type") == "proposal":
            proposal_usd += usd["total_usd"]
            if r.get("status") == "completed":
                proposal_count += 1
        elif r.get("run_type") == "discovery":
            discovery_usd += usd["total_usd"]
            n = int(r.get("candidate_count") or 0)
            # Fall back to default 25 candidates per discovery run when
            # the record didn't carry a count (e.g. mid-run).
            discovery_targets += n if n > 0 else 25
    return {
        "per_proposal_usd": (
            round(proposal_usd / proposal_count, 6) if proposal_count > 0 else None
        ),
        "per_discovery_target_usd": (
            round(discovery_usd / discovery_targets, 6)
            if discovery_targets > 0
            else None
        ),
    }


def budget_state(
    records: Iterable[dict[str, Any]],
    pricing: Pricing,
    budget: CostBudget,
    today: date,
) -> dict[str, Any]:
    used = 0.0
    for r in records:
        d = _parse_iso_date(r.get("created_at") or "")
        if d is None or not _is_same_month(d, today):
            continue
        usd = usd_for_run(r.get("usage") or {}, r.get("model") or "", pricing)
        used += usd["total_usd"]
    monthly = float(budget.monthly_usd)
    warn = float(budget.warn_pct)
    pct = (used / monthly) if monthly > 0 else 0.0
    return {
        "monthly_usd": monthly,
        "used_usd": round(used, 6),
        "used_pct": pct,
        "warn_pct": warn,
        "breached": pct >= warn,
        "over_budget": pct >= 1.0,
    }


def recent_runs_with_usd(
    records: Iterable[dict[str, Any]],
    pricing: Pricing,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    sorted_records = sorted(
        records,
        key=lambda r: r.get("created_at") or "",
        reverse=True,
    )
    out: list[dict[str, Any]] = []
    for r in sorted_records[:limit]:
        usage = r.get("usage") or {}
        usd = usd_for_run(usage, r.get("model") or "", pricing)
        out.append(
            {
                "run_id": r.get("run_id") or "",
                "created_at": r.get("created_at") or "",
                "run_type": r.get("run_type") or "unknown",
                "model": r.get("model") or "",
                "label": r.get("label") or "",
                "tokens": {
                    "input": int(usage.get("input_tokens") or 0),
                    "output": int(usage.get("output_tokens") or 0),
                    "cache_read": int(usage.get("cache_read_input_tokens") or 0),
                    "cache_write": int(
                        usage.get("cache_creation_input_tokens") or 0
                    ),
                },
                "usd": round(usd["total_usd"], 6),
            }
        )
    return out


def now_utc_date() -> date:
    return datetime.now(timezone.utc).date()
