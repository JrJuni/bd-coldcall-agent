"use client";

import { useEffect, useState } from "react";

import ActiveModelSelector from "@/components/cost/ActiveModelSelector";
import BudgetBar from "@/components/cost/BudgetBar";
import CostBreakdownBars from "@/components/cost/CostBreakdownBars";
import CostTrendChart from "@/components/cost/CostTrendChart";
import KpiCards from "@/components/cost/KpiCards";
import PerUnitCard from "@/components/cost/PerUnitCard";
import PricingBudgetEditor from "@/components/cost/PricingBudgetEditor";
import RecentRunsTable from "@/components/cost/RecentRunsTable";
import { getCostSummary } from "@/lib/api";
import type { CostSummaryResponse } from "@/lib/types";

export default function CostPage() {
  const [data, setData] = useState<CostSummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [days, setDays] = useState<number>(30);
  const [dim, setDim] = useState<"model" | "run_type">("run_type");

  async function refresh(d: number = days) {
    try {
      const r = await getCostSummary(d);
      setData(r);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh(days);
  }, [days]); // eslint-disable-line react-hooks/exhaustive-deps

  const empty =
    data != null &&
    data.kpi.cumulative_usd === 0 &&
    data.recent_runs.length === 0;

  return (
    <div className="space-y-5">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Cost Explorer</h1>
          <p className="mt-1 text-sm text-slate-500">
            Sonnet/Haiku 호출 + 검색 비용을 한 곳에 모았습니다. Anthropic prompt
            caching 절감 효과, 단가 메트릭, 월 예산 트래킹까지 — 단가표 변경은
            하단 폼/YAML 에서.
          </p>
        </div>
        <div className="flex flex-shrink-0 items-center gap-2">
          <ActiveModelSelector onChanged={() => refresh(days)} />
          <button
            type="button"
            onClick={() => refresh(days)}
            className="rounded border border-slate-300 px-3 py-1.5 text-xs hover:bg-slate-50"
          >
            새로고침
          </button>
        </div>
      </header>

      {loading && <p className="text-sm text-slate-500">불러오는 중...</p>}
      {error && <p className="text-sm text-rose-600">{error}</p>}

      {data && (
        <>
          <KpiCards kpi={data.kpi} />

          {empty && (
            <section className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-6">
              <p className="text-sm text-slate-700">
                아직 실행된 run 이 없습니다. <b>Proposals</b> 또는{" "}
                <b>Discovery</b> 페이지에서 첫 실행을 시작하면 여기에 비용이
                집계됩니다.
              </p>
              <p className="mt-1 text-xs text-slate-500">
                단가표·월 예산은 아래에서 미리 세팅해 둘 수 있습니다.
              </p>
            </section>
          )}

          <CostTrendChart
            data={data.daily_series}
            days={days}
            onDaysChange={setDays}
          />

          <div className="grid gap-5 lg:grid-cols-2">
            <CostBreakdownBars
              byModel={data.by_model}
              byRunType={data.by_run_type}
              dim={dim}
              onDimChange={setDim}
            />
            <PerUnitCard data={data.per_unit} />
          </div>

          <BudgetBar budget={data.budget} />

          <RecentRunsTable runs={data.recent_runs} />

          <PricingBudgetEditor onSaved={() => refresh(days)} />

          <p className="text-right text-xs text-slate-400">
            generated_at {data.generated_at}
          </p>
        </>
      )}
    </div>
  );
}
