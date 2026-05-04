"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import type { CostRecentRun } from "@/lib/types";

const PAGE_SIZE = 10;

function fmtUsd(v: number): string {
  if (v < 0.01) return `$${v.toFixed(4)}`;
  return `$${v.toFixed(2)}`;
}

function fmtDate(iso: string): string {
  if (!iso) return "—";
  return iso.slice(0, 16).replace("T", " ");
}

function TokenBars({ t }: { t: CostRecentRun["tokens"] }) {
  const total = t.input + t.output + t.cache_read + t.cache_write;
  if (total === 0) return <span className="text-xs text-slate-400">—</span>;
  const seg = (n: number, color: string, label: string) => {
    if (n === 0) return null;
    const pct = (n / total) * 100;
    return (
      <span
        title={`${label}: ${n.toLocaleString()}`}
        className={`inline-block h-2 ${color}`}
        style={{ width: `${pct}%` }}
      />
    );
  };
  return (
    <span className="inline-flex w-32 items-center overflow-hidden rounded bg-slate-100">
      {seg(t.input, "bg-slate-700", "input")}
      {seg(t.output, "bg-blue-500", "output")}
      {seg(t.cache_read, "bg-emerald-500", "cache_read")}
      {seg(t.cache_write, "bg-amber-500", "cache_write")}
    </span>
  );
}

export default function RecentRunsTable({ runs }: { runs: CostRecentRun[] }) {
  const [page, setPage] = useState(0);
  const pages = Math.max(1, Math.ceil(runs.length / PAGE_SIZE));
  const slice = useMemo(
    () => runs.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE),
    [runs, page],
  );

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-slate-700">최근 실행</h2>
          <p className="text-xs text-slate-500">
            전체 {runs.length}건 · 토큰 비율 막대(input/output/cache_read/cache_write)
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
            className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40 hover:bg-slate-50"
          >
            ← 이전
          </button>
          <span className="tabular-nums text-slate-500">
            {page + 1} / {pages}
          </span>
          <button
            type="button"
            onClick={() => setPage((p) => Math.min(pages - 1, p + 1))}
            disabled={page >= pages - 1}
            className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40 hover:bg-slate-50"
          >
            다음 →
          </button>
        </div>
      </div>
      {runs.length === 0 ? (
        <p className="text-sm text-slate-500">
          아직 실행 기록이 없습니다. Proposals / Discovery 페이지에서 첫 실행을
          시작해보세요.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-slate-200 text-slate-500">
              <tr>
                <th className="py-2 pr-3 font-normal">시각</th>
                <th className="py-2 pr-3 font-normal">유형</th>
                <th className="py-2 pr-3 font-normal">대상</th>
                <th className="py-2 pr-3 font-normal">모델</th>
                <th className="py-2 pr-3 font-normal">토큰</th>
                <th className="py-2 text-right font-normal">USD</th>
              </tr>
            </thead>
            <tbody>
              {slice.map((r) => (
                <tr
                  key={r.run_id}
                  className="border-b border-slate-100 hover:bg-slate-50"
                >
                  <td className="py-2 pr-3 font-mono tabular-nums text-slate-600">
                    {fmtDate(r.created_at)}
                  </td>
                  <td className="py-2 pr-3">
                    <span
                      className={
                        "rounded px-1.5 py-0.5 text-[10px] " +
                        (r.run_type === "proposal"
                          ? "bg-blue-100 text-blue-800"
                          : r.run_type === "discovery"
                          ? "bg-violet-100 text-violet-800"
                          : r.run_type === "rag_summary"
                          ? "bg-amber-100 text-amber-800"
                          : "bg-slate-100 text-slate-700")
                      }
                    >
                      {r.run_type}
                    </span>
                  </td>
                  <td className="py-2 pr-3 text-slate-700">
                    {r.run_type === "proposal" ? (
                      <Link
                        href={`/runs/${encodeURIComponent(r.run_id)}`}
                        className="hover:underline"
                      >
                        {r.label || r.run_id}
                      </Link>
                    ) : (
                      <span>{r.label || r.run_id}</span>
                    )}
                  </td>
                  <td className="py-2 pr-3 font-mono text-[10px] text-slate-500">
                    {r.model.replace("claude-", "")}
                  </td>
                  <td className="py-2 pr-3">
                    <TokenBars t={r.tokens} />
                  </td>
                  <td className="py-2 text-right font-mono tabular-nums text-slate-900">
                    {fmtUsd(r.usd)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
