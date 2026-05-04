"use client";

import type { CostBudgetState } from "@/lib/types";

export default function BudgetBar({ budget }: { budget: CostBudgetState }) {
  const pct = Math.min(1, Math.max(0, budget.used_pct));
  const overflow = budget.used_pct > 1;
  const tone = budget.over_budget
    ? "bg-rose-500"
    : budget.breached
    ? "bg-amber-500"
    : "bg-emerald-500";
  const bgTone = budget.over_budget
    ? "bg-rose-50 border-rose-200"
    : budget.breached
    ? "bg-amber-50 border-amber-200"
    : "bg-white border-slate-200";

  return (
    <section className={`rounded-lg border p-5 shadow-sm ${bgTone}`}>
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-slate-700">월 예산</h2>
          <p className="text-xs text-slate-500">
            warn ≥ {(budget.warn_pct * 100).toFixed(0)}% · over &gt; 100%
          </p>
        </div>
        <p className="font-mono text-sm tabular-nums text-slate-700">
          ${budget.used_usd.toFixed(2)} / ${budget.monthly_usd.toFixed(2)}
          {overflow && (
            <span className="ml-2 rounded-full bg-rose-200 px-2 py-0.5 text-xs font-semibold text-rose-900">
              초과
            </span>
          )}
          {!overflow && budget.breached && (
            <span className="ml-2 rounded-full bg-amber-200 px-2 py-0.5 text-xs font-semibold text-amber-900">
              경고
            </span>
          )}
        </p>
      </div>
      <div className="mt-3 h-3 w-full overflow-hidden rounded-full bg-slate-200">
        <div
          className={`h-full ${tone} transition-all`}
          style={{ width: `${pct * 100}%` }}
        />
      </div>
      <p className="mt-1 text-right text-xs tabular-nums text-slate-500">
        {(budget.used_pct * 100).toFixed(1)}% used
      </p>
    </section>
  );
}
