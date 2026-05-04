"use client";

import type { CostPerUnit } from "@/lib/types";

function fmt(v: number | null): string {
  if (v == null) return "—";
  if (v < 0.01) return `$${v.toFixed(4)}`;
  return `$${v.toFixed(2)}`;
}

export default function PerUnitCard({ data }: { data: CostPerUnit }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-sm font-semibold text-slate-700">단가 (Per-Unit)</h2>
      <p className="text-xs text-slate-500">
        실제 결과물 1개당 평균 비용 — 단가 변경 후 즉시 반영됩니다.
      </p>
      <div className="mt-3 grid grid-cols-2 gap-3">
        <div className="rounded border border-slate-100 bg-slate-50 p-3">
          <p className="text-xs text-slate-500">제안서 1건당</p>
          <p className="font-mono text-xl tabular-nums text-slate-900">
            {fmt(data.per_proposal_usd)}
          </p>
          <p className="mt-1 text-xs text-slate-400">
            {data.per_proposal_usd == null
              ? "완료된 proposal run 없음"
              : "completed 기준 평균"}
          </p>
        </div>
        <div className="rounded border border-slate-100 bg-slate-50 p-3">
          <p className="text-xs text-slate-500">Discovery 후보 1건당</p>
          <p className="font-mono text-xl tabular-nums text-slate-900">
            {fmt(data.per_discovery_target_usd)}
          </p>
          <p className="mt-1 text-xs text-slate-400">
            {data.per_discovery_target_usd == null
              ? "discovery run 없음"
              : "후보 수로 나눈 평균"}
          </p>
        </div>
      </div>
    </section>
  );
}
