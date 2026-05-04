"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { CostBreakdownItem } from "@/lib/types";

const COLORS = ["#0f172a", "#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6"];

export default function CostBreakdownBars({
  byModel,
  byRunType,
  dim,
  onDimChange,
}: {
  byModel: CostBreakdownItem[];
  byRunType: CostBreakdownItem[];
  dim: "model" | "run_type";
  onDimChange: (d: "model" | "run_type") => void;
}) {
  const data = dim === "model" ? byModel : byRunType;
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-slate-700">
            비용 분해 (USD)
          </h2>
          <p className="text-xs text-slate-500">
            {dim === "model" ? "모델별" : "런타입별"} · 누적
          </p>
        </div>
        <div className="flex gap-1 text-xs">
          <button
            type="button"
            onClick={() => onDimChange("model")}
            className={
              "rounded border px-2 py-1 transition " +
              (dim === "model"
                ? "border-slate-900 bg-slate-900 text-white"
                : "border-slate-300 text-slate-600 hover:bg-slate-50")
            }
          >
            모델별
          </button>
          <button
            type="button"
            onClick={() => onDimChange("run_type")}
            className={
              "rounded border px-2 py-1 transition " +
              (dim === "run_type"
                ? "border-slate-900 bg-slate-900 text-white"
                : "border-slate-300 text-slate-600 hover:bg-slate-50")
            }
          >
            런타입별
          </button>
        </div>
      </div>
      {data.length === 0 ? (
        <p className="text-xs text-slate-500">아직 집계할 데이터가 없습니다.</p>
      ) : (
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} layout="vertical">
              <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" />
              <XAxis
                type="number"
                tick={{ fontSize: 10, fill: "#64748b" }}
                tickFormatter={(v: number) => `$${v.toFixed(2)}`}
              />
              <YAxis
                type="category"
                dataKey="label"
                tick={{ fontSize: 11, fill: "#334155" }}
                width={140}
              />
              <Tooltip
                formatter={(v: number) => [`$${Number(v).toFixed(4)}`, "USD"]}
                contentStyle={{ fontSize: 12 }}
              />
              <Bar dataKey="usd">
                {data.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}
