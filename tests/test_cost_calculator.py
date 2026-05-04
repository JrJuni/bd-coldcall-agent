"""Cost Explorer calculator unit tests.

Pure functions over fixture record dicts — no API or store coupling.
"""
from __future__ import annotations

from datetime import date

import pytest

from src.config.schemas import CostBudget, ModelRates, Pricing
from src.cost import calculator as calc


@pytest.fixture
def pricing() -> Pricing:
    return Pricing(
        llm={
            "claude-sonnet-4-6": ModelRates(
                input_per_mtok=3.0,
                output_per_mtok=15.0,
                cache_read_per_mtok=0.30,
                cache_write_per_mtok=3.75,
            ),
        }
    )


@pytest.fixture
def records() -> list[dict]:
    """Five records: 3 proposal (one this month, one last, one further),
    2 discovery (this month + last month). Tokens chosen for round USD."""
    return [
        # Proposal — this month, 1M input + 100K output → $4.50
        {
            "run_id": "r1",
            "created_at": "2026-05-02T10:00:00+00:00",
            "run_type": "proposal",
            "model": "claude-sonnet-4-6",
            "usage": {"input_tokens": 1_000_000, "output_tokens": 100_000},
            "label": "Acme · fin",
            "status": "completed",
        },
        # Proposal — this month, with cache reads (savings)
        {
            "run_id": "r2",
            "created_at": "2026-05-03T10:00:00+00:00",
            "run_type": "proposal",
            "model": "claude-sonnet-4-6",
            "usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_input_tokens": 1_000_000,
                "cache_creation_input_tokens": 0,
            },
            "label": "Beta · fin",
            "status": "completed",
        },
        # Proposal — last month
        {
            "run_id": "r3",
            "created_at": "2026-04-15T10:00:00+00:00",
            "run_type": "proposal",
            "model": "claude-sonnet-4-6",
            "usage": {"input_tokens": 500_000, "output_tokens": 50_000},
            "label": "Gamma · fin",
            "status": "completed",
        },
        # Discovery — this month, 25 candidates
        {
            "run_id": "d1",
            "created_at": "2026-05-04T08:00:00+00:00",
            "run_type": "discovery",
            "model": "claude-sonnet-4-6",
            "usage": {"input_tokens": 200_000, "output_tokens": 20_000},
            "label": "default · databricks",
            "status": "completed",
            "candidate_count": 25,
        },
        # Discovery — last month
        {
            "run_id": "d2",
            "created_at": "2026-04-10T08:00:00+00:00",
            "run_type": "discovery",
            "model": "claude-sonnet-4-6",
            "usage": {"input_tokens": 100_000, "output_tokens": 10_000},
            "label": "default · databricks",
            "status": "completed",
            "candidate_count": 25,
        },
    ]


def test_usd_for_run_basic(pricing):
    usd = calc.usd_for_run(
        {"input_tokens": 1_000_000, "output_tokens": 100_000},
        "claude-sonnet-4-6",
        pricing,
    )
    assert usd["input_usd"] == pytest.approx(3.0)
    assert usd["output_usd"] == pytest.approx(1.5)
    assert usd["total_usd"] == pytest.approx(4.5)
    assert usd["cache_savings_usd"] == 0.0


def test_usd_for_run_cache_savings(pricing):
    usd = calc.usd_for_run(
        {"cache_read_input_tokens": 1_000_000},
        "claude-sonnet-4-6",
        pricing,
    )
    # Savings = 1M * (3.0 - 0.3) / 1M = $2.70
    assert usd["cache_savings_usd"] == pytest.approx(2.7)
    assert usd["cache_read_usd"] == pytest.approx(0.3)


def test_usd_for_run_unknown_model_zero_rate(pricing):
    usd = calc.usd_for_run(
        {"input_tokens": 1_000_000}, "claude-bogus-9000", pricing
    )
    assert usd["total_usd"] == 0.0


def test_kpi_block_partitions_months(records, pricing):
    today = date(2026, 5, 4)
    kpi = calc.kpi_block(records, pricing, today)
    # this month: r1 ($4.50) + r2 ($0.30) + d1 (0.6 + 0.3 = $0.9) = $5.70
    assert kpi["this_month_usd"] == pytest.approx(5.7)
    # last month: r3 ($1.5+0.75=$2.25) + d2 ($0.3+0.15=$0.45) = $2.70
    assert kpi["last_month_usd"] == pytest.approx(2.7)
    # cumulative = sum of all
    assert kpi["cumulative_usd"] == pytest.approx(5.7 + 2.7)
    # cache savings only from r2
    assert kpi["cache_savings_usd"] == pytest.approx(2.7)


def test_aggregate_daily_window_and_zero_fill(records, pricing):
    today = date(2026, 5, 4)
    series = calc.aggregate_daily(records, pricing, days=7, today=today)
    assert len(series) == 7
    # Trailing day = 2026-05-04, has d1 (0.9 USD)
    assert series[-1]["date"] == "2026-05-04"
    assert series[-1]["usd"] == pytest.approx(0.9)
    # 2026-05-02 has r1 (4.5)
    by_date = {p["date"]: p["usd"] for p in series}
    assert by_date["2026-05-02"] == pytest.approx(4.5)
    assert by_date["2026-05-03"] == pytest.approx(0.3)
    # 2026-04-30 in window but no records
    assert by_date["2026-04-30"] == 0.0


def test_aggregate_by_run_type(records, pricing):
    today = date(2026, 5, 4)
    out = calc.aggregate_by(records, pricing, dim="run_type")
    by_label = {item["label"]: item for item in out}
    assert "proposal" in by_label
    assert "discovery" in by_label
    # proposal cumulative = r1 + r2 + r3 = 4.5 + 0.3 + 2.25 = 7.05
    assert by_label["proposal"]["usd"] == pytest.approx(7.05)


def test_per_unit(records, pricing):
    p = calc.per_unit(records, pricing)
    # 3 completed proposals, total proposal usd 7.05 → 2.35 per
    assert p["per_proposal_usd"] == pytest.approx(7.05 / 3)
    # 2 discovery × 25 = 50 candidates, total 0.9 + 0.45 = 1.35
    assert p["per_discovery_target_usd"] == pytest.approx(1.35 / 50)


def test_budget_state_breach_thresholds(records, pricing):
    today = date(2026, 5, 4)
    # Tight budget triggers breach
    tight = CostBudget(monthly_usd=5.0, warn_pct=0.8)
    state = calc.budget_state(records, pricing, tight, today)
    assert state["used_usd"] == pytest.approx(5.7)
    assert state["used_pct"] == pytest.approx(5.7 / 5.0)
    assert state["breached"] is True
    assert state["over_budget"] is True

    # Loose budget — under threshold
    loose = CostBudget(monthly_usd=100.0, warn_pct=0.8)
    state2 = calc.budget_state(records, pricing, loose, today)
    assert state2["breached"] is False
    assert state2["over_budget"] is False


def test_recent_runs_sorted_desc(records, pricing):
    out = calc.recent_runs_with_usd(records, pricing, limit=3)
    assert len(out) == 3
    # Newest first by created_at
    assert out[0]["run_id"] == "d1"
    assert out[1]["run_id"] == "r2"
    assert out[2]["run_id"] == "r1"


def test_empty_records_returns_zeros(pricing):
    today = date(2026, 5, 4)
    kpi = calc.kpi_block([], pricing, today)
    assert kpi["this_month_usd"] == 0.0
    assert kpi["cache_savings_pct"] == 0.0
    series = calc.aggregate_daily([], pricing, days=3, today=today)
    assert [p["usd"] for p in series] == [0.0, 0.0, 0.0]
    p = calc.per_unit([], pricing)
    assert p["per_proposal_usd"] is None
    assert p["per_discovery_target_usd"] is None
