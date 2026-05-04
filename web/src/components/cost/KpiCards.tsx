"use client";

import type { CostKpi } from "@/lib/types";

function fmtUsd(v: number): string {
  if (v === 0) return "$0.00";
  if (v < 0.01) return `$${v.toFixed(4)}`;
  return `$${v.toFixed(2)}`;
}

function fmtPct(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

function Card({
  title,
  value,
  hint,
  emphasis = false,
}: {
  title: string;
  value: string;
  hint?: string;
  emphasis?: boolean;
}) {
  return (
    <div
      className={
        "rounded-lg border p-4 shadow-sm " +
        (emphasis
          ? "border-emerald-200 bg-emerald-50"
          : "border-slate-200 bg-white")
      }
    >
      <p className="text-xs uppercase tracking-wide text-slate-500">{title}</p>
      <p
        className={
          "mt-1 font-mono text-2xl tabular-nums " +
          (emphasis ? "text-emerald-800" : "text-slate-900")
        }
      >
        {value}
      </p>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

export default function KpiCards({ kpi }: { kpi: CostKpi }) {
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Card title="이번 달" value={fmtUsd(kpi.this_month_usd)} />
      <Card title="지난 달" value={fmtUsd(kpi.last_month_usd)} />
      <Card title="누적" value={fmtUsd(kpi.cumulative_usd)} />
      <Card
        title="캐시 절감"
        value={fmtUsd(kpi.cache_savings_usd)}
        hint={`Anthropic prompt caching · ${fmtPct(kpi.cache_savings_pct)} saved`}
        emphasis
      />
    </div>
  );
}
