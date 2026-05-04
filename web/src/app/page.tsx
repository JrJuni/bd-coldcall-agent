"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import TargetStageBadge from "@/components/TargetStageBadge";
import TierBadge from "@/components/TierBadge";
import { getDashboard } from "@/lib/api";
import type {
  DashboardCostSummary,
  DashboardNewsMini,
  DashboardRagStatus,
  DashboardRecentDiscovery,
  DashboardRecentRun,
  DashboardResponse,
} from "@/lib/types";
import { TARGET_STAGES, type TargetStage, type Tier } from "@/lib/types";

export default function HomePage() {
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    try {
      const r = await getDashboard();
      setData(r);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  return (
    <div className="space-y-6">
      <header className="flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-semibold">BD Cold-Call Agent</h1>
          <p className="mt-2 text-sm text-slate-500">
            타겟 발굴 → 제안서 → 콜 → 기록 까지의 BD 일상 운영을 한 화면에서
            관리합니다.
          </p>
        </div>
        <button
          type="button"
          onClick={refresh}
          className="rounded border border-slate-300 px-3 py-1.5 text-xs hover:bg-slate-50"
        >
          새로고침
        </button>
      </header>

      {loading && <p className="text-sm text-slate-500">불러오는 중...</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {data && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          <QuickRunBox />
          <NewsBox news={data.news} />
          <PipelineBox stages={data.pipeline_by_stage} />
          <ProposalsBox
            runs={data.recent_runs}
            discovery={data.recent_discovery}
          />
          <RagBox rag={data.rag} />
          <CostBox cost={data.cost} />
        </div>
      )}

      {data && (
        <p className="text-xs text-slate-400">
          generated_at {data.generated_at} · interactions{" "}
          {data.interactions_count}
        </p>
      )}
    </div>
  );
}

function Box({
  title,
  href,
  children,
}: {
  title: string;
  href?: string;
  children: React.ReactNode;
}) {
  const inner = (
    <div className="h-full rounded-lg border border-slate-200 bg-white p-5 shadow-sm transition hover:border-slate-300">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-700">{title}</h2>
        {href && (
          <span className="text-xs text-slate-400" aria-hidden>
            열기 →
          </span>
        )}
      </div>
      <div className="mt-3">{children}</div>
    </div>
  );
  return href ? <Link href={href}>{inner}</Link> : inner;
}

function QuickRunBox() {
  return (
    <Box title="Quick Run" href="/proposals/new">
      <p className="text-sm text-slate-700">
        회사 + 산업 키워드만 넣으면 즉시 BD 제안서 초안을 생성합니다.
      </p>
      <p className="mt-2 text-xs text-slate-500">
        Sonnet 2 회 호출 · ~$0.30 · ~3분
      </p>
    </Box>
  );
}

function NewsBox({ news }: { news: DashboardNewsMini | null }) {
  return (
    <Box title="오늘의 뉴스 mini" href="/news">
      {news ? (
        <>
          <p className="text-xs text-slate-500">
            {news.namespace} · seed “{news.seed_query ?? "—"}” · {news.article_count}
            건 · {news.generated_at.slice(0, 10)}
          </p>
          <ul className="mt-2 space-y-1 text-sm text-slate-700">
            {news.top_titles.length === 0 && (
              <li className="text-slate-400">결과 없음</li>
            )}
            {news.top_titles.map((t, i) => (
              <li key={i} className="line-clamp-1">
                · {t}
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="text-sm text-slate-500">
          아직 캐시된 뉴스가 없습니다. /news 에서 Refresh 하세요.
        </p>
      )}
    </Box>
  );
}

function PipelineBox({ stages }: { stages: Record<string, number> }) {
  const total = Object.values(stages).reduce((a, b) => a + b, 0);
  return (
    <Box title="Pipeline 요약" href="/targets">
      {total === 0 ? (
        <p className="text-sm text-slate-500">
          아직 등록된 타겟이 없습니다.
        </p>
      ) : (
        <ul className="space-y-1 text-sm">
          {TARGET_STAGES.map((s: TargetStage) => (
            <li
              key={s}
              className="flex items-center justify-between"
            >
              <TargetStageBadge stage={s} />
              <span className="tabular-nums text-slate-700">
                {stages[s] ?? 0}
              </span>
            </li>
          ))}
          <li className="mt-1 flex justify-between border-t border-slate-100 pt-1 text-xs text-slate-500">
            <span>합계</span>
            <span className="tabular-nums">{total}</span>
          </li>
        </ul>
      )}
    </Box>
  );
}

function ProposalsBox({
  runs,
  discovery,
}: {
  runs: DashboardRecentRun[];
  discovery: DashboardRecentDiscovery | null;
}) {
  return (
    <Box title="Recent Proposals & Discovery" href="/proposals">
      {runs.length === 0 && !discovery && (
        <p className="text-sm text-slate-500">최근 활동이 없습니다.</p>
      )}
      {runs.length > 0 && (
        <ul className="space-y-1 text-sm">
          {runs.slice(0, 3).map((r) => (
            <li
              key={r.run_id}
              className="flex items-center justify-between"
            >
              <Link
                href={`/runs/${encodeURIComponent(r.run_id)}`}
                className="truncate text-slate-700 hover:underline"
                onClick={(e) => e.stopPropagation()}
              >
                {r.company} ·{" "}
                <span className="text-xs text-slate-500">{r.industry}</span>
              </Link>
              <span className="ml-2 text-xs text-slate-500">{r.status}</span>
            </li>
          ))}
        </ul>
      )}
      {discovery && (
        <div className="mt-3 rounded border border-slate-100 bg-slate-50 px-3 py-2">
          <p className="text-xs text-slate-500">
            Discovery latest · {discovery.namespace} · {discovery.product}
          </p>
          <div className="mt-1 flex flex-wrap gap-1.5 text-xs">
            {(["S", "A", "B", "C"] as Tier[]).map((t) => (
              <span key={t} className="inline-flex items-center gap-1">
                <TierBadge tier={t} />
                <span className="tabular-nums text-slate-700">
                  {discovery.tier_distribution[t] ?? 0}
                </span>
              </span>
            ))}
          </div>
        </div>
      )}
    </Box>
  );
}

function RagBox({ rag }: { rag: DashboardRagStatus[] }) {
  const indexed = rag.filter((n) => n.is_indexed);
  return (
    <Box title="RAG 상태" href="/rag">
      {rag.length === 0 ? (
        <p className="text-sm text-slate-500">namespace 가 없습니다.</p>
      ) : (
        <ul className="space-y-1 text-sm">
          {rag.slice(0, 4).map((n) => (
            <li
              key={n.namespace}
              className="flex items-center justify-between"
            >
              <span className="truncate text-slate-700">
                {n.namespace}
                {n.namespace === "default" && (
                  <span className="ml-1 text-xs text-slate-400">(default)</span>
                )}
              </span>
              <span className="tabular-nums text-xs text-slate-500">
                {n.document_count} docs · {n.chunk_count} chunks
              </span>
            </li>
          ))}
        </ul>
      )}
      {indexed.length === 0 && (
        <p className="mt-2 text-xs text-amber-700">
          인덱싱된 문서가 없습니다 — RAG 탭에서 업로드 후 Re-index.
        </p>
      )}
    </Box>
  );
}

function CostBox({ cost }: { cost: DashboardCostSummary }) {
  const fmt = (v: number) =>
    v < 0.01 && v > 0 ? `$${v.toFixed(4)}` : `$${v.toFixed(2)}`;
  const badge = cost.over_budget ? (
    <span className="rounded-full bg-rose-200 px-2 py-0.5 text-[10px] font-semibold text-rose-900">
      예산 초과
    </span>
  ) : cost.breached ? (
    <span className="rounded-full bg-amber-200 px-2 py-0.5 text-[10px] font-semibold text-amber-900">
      예산 경고
    </span>
  ) : null;
  return (
    <Box title="비용 (USD)" href="/cost">
      <div className="flex items-baseline justify-between">
        <p className="font-mono text-2xl tabular-nums text-slate-900">
          {fmt(cost.this_month_usd)}
        </p>
        {badge}
      </div>
      <p className="mt-1 text-xs text-slate-500">
        이번 달 · 누적 {fmt(cost.cumulative_usd)} · 캐시 절감{" "}
        {fmt(cost.cache_savings_usd)} ({(cost.cache_savings_pct * 100).toFixed(0)}%)
      </p>
      {cost.monthly_budget_usd > 0 && (
        <div className="mt-2">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-200">
            <div
              className={
                cost.over_budget
                  ? "h-full bg-rose-500"
                  : cost.breached
                  ? "h-full bg-amber-500"
                  : "h-full bg-emerald-500"
              }
              style={{
                width: `${Math.min(100, cost.used_pct * 100).toFixed(1)}%`,
              }}
            />
          </div>
          <p className="mt-1 text-right text-xs tabular-nums text-slate-500">
            {(cost.used_pct * 100).toFixed(0)}% / ${cost.monthly_budget_usd.toFixed(0)}
          </p>
        </div>
      )}
    </Box>
  );
}
