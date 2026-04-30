"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import EmptyState from "@/components/EmptyState";
import { listRuns } from "@/lib/api";
import type { RunSummary } from "@/lib/types";

export default function ProposalsPage() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await listRuns();
        if (!cancelled) setRuns(r.runs);
      } catch (err) {
        if (!cancelled)
          setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Proposals</h1>
          <p className="mt-1 text-sm text-slate-500">
            제안서 작성 이력. 행을 클릭해서 상세·편집·다운로드.
          </p>
        </div>
        <Link
          href="/proposals/new"
          className="rounded-md bg-slate-900 px-4 py-2 text-sm text-white hover:bg-slate-800"
        >
          + 새 제안서
        </Link>
      </div>

      {loading && <p className="text-sm text-slate-500">불러오는 중...</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {!loading && runs.length === 0 && (
        <EmptyState
          title="아직 작성된 제안서가 없습니다."
          description="우측 상단 '새 제안서' 또는 Targets 탭에서 회사를 선택해 시작하세요."
          ctaLabel="새 제안서"
          ctaHref="/proposals/new"
        />
      )}

      {runs.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50 text-left text-xs">
              <tr>
                <th className="px-4 py-2 font-medium text-slate-700">Company</th>
                <th className="px-4 py-2 font-medium text-slate-700">Industry</th>
                <th className="px-4 py-2 font-medium text-slate-700">Lang</th>
                <th className="px-4 py-2 font-medium text-slate-700">Status</th>
                <th className="px-4 py-2 font-medium text-slate-700">Created</th>
                <th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {runs.map((r) => (
                <tr key={r.run_id} className="hover:bg-slate-50">
                  <td className="px-4 py-2 font-medium text-slate-900">
                    <Link
                      href={`/runs/${encodeURIComponent(r.run_id)}`}
                      className="hover:underline"
                    >
                      {r.company}
                    </Link>
                  </td>
                  <td className="px-4 py-2 text-slate-700">{r.industry}</td>
                  <td className="px-4 py-2 text-xs uppercase text-slate-500">
                    {r.lang}
                  </td>
                  <td className="px-4 py-2 text-xs">
                    <StatusPill status={r.status} />
                  </td>
                  <td className="px-4 py-2 text-xs text-slate-500">
                    {r.created_at.slice(0, 19).replace("T", " ")}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <Link
                      href={`/runs/${encodeURIComponent(r.run_id)}`}
                      className="text-xs font-medium text-blue-600 hover:underline"
                    >
                      열기 →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const styles =
    status === "completed"
      ? "bg-emerald-100 text-emerald-800"
      : status === "failed"
        ? "bg-rose-100 text-rose-800"
        : status === "running"
          ? "bg-blue-100 text-blue-800"
          : "bg-slate-100 text-slate-700";
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${styles}`}
    >
      {status}
    </span>
  );
}
