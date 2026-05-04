"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { CostDailyPoint } from "@/lib/types";

export default function CostTrendChart({
  data,
  days,
  onDaysChange,
}: {
  data: CostDailyPoint[];
  days: number;
  onDaysChange: (n: number) => void;
}) {
  const total = data.reduce((s, p) => s + p.usd, 0);
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-slate-700">
            일자별 비용 추이
          </h2>
          <p className="text-xs text-slate-500">
            최근 {days}일 합계 ${total.toFixed(2)}
          </p>
        </div>
        <div className="flex gap-1 text-xs">
          {[30, 60, 90].map((n) => (
            <button
              key={n}
              type="button"
              onClick={() => onDaysChange(n)}
              className={
                "rounded border px-2 py-1 transition " +
                (n === days
                  ? "border-slate-900 bg-slate-900 text-white"
                  : "border-slate-300 text-slate-600 hover:bg-slate-50")
              }
            >
              {n}일
            </button>
          ))}
        </div>
      </div>
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data}>
            <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 10, fill: "#64748b" }}
              tickFormatter={(v: string) => v.slice(5)}
            />
            <YAxis
              tick={{ fontSize: 10, fill: "#64748b" }}
              tickFormatter={(v: number) => `$${v.toFixed(2)}`}
            />
            <Tooltip
              formatter={(v: number) => [`$${Number(v).toFixed(4)}`, "USD"]}
              labelFormatter={(l: string) => l}
              contentStyle={{ fontSize: 12 }}
            />
            <Line
              type="monotone"
              dataKey="usd"
              stroke="#0f172a"
              strokeWidth={2}
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}
