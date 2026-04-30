"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import CandidateTable from "@/components/CandidateTable";
import DiscoveryRunForm from "@/components/DiscoveryRunForm";
import EmptyState from "@/components/EmptyState";
import WeightSliders from "@/components/WeightSliders";
import {
  deleteDiscoveryRun,
  discoveryEventsUrl,
  getDiscoveryRun,
  listDiscoveryRuns,
  recomputeDiscovery,
} from "@/lib/api";
import type {
  DiscoveryRunDetail,
  DiscoveryRunSummary,
  WeightDimension,
} from "@/lib/types";

export default function DiscoverPage() {
  const [runs, setRuns] = useState<DiscoveryRunSummary[]>([]);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [activeRun, setActiveRun] = useState<DiscoveryRunDetail | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [recomputing, setRecomputing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const sseRef = useRef<EventSource | null>(null);

  const refreshRunsList = useCallback(async () => {
    try {
      const r = await listDiscoveryRuns();
      setRuns(r.runs);
      return r.runs;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return [];
    }
  }, []);

  const refreshActiveRun = useCallback(async (runId: string) => {
    try {
      const detail = await getDiscoveryRun(runId);
      setActiveRun(detail);
      setRuns((prev) => {
        const idx = prev.findIndex((r) => r.run_id === runId);
        if (idx === -1) return prev;
        const next = [...prev];
        next[idx] = detail;
        return next;
      });
      return detail;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return null;
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const list = await refreshRunsList();
      if (cancelled) return;
      if (list.length > 0) {
        const newest = list[0].run_id;
        setActiveRunId(newest);
        await refreshActiveRun(newest);
      }
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [refreshRunsList, refreshActiveRun]);

  useEffect(() => {
    if (sseRef.current) {
      sseRef.current.close();
      sseRef.current = null;
    }
    if (!activeRunId) return;
    const detail = activeRun;
    if (
      detail &&
      (detail.status === "completed" || detail.status === "failed")
    ) {
      return;
    }
    const es = new EventSource(discoveryEventsUrl(activeRunId));
    sseRef.current = es;
    const onAny = () => {
      void refreshActiveRun(activeRunId);
    };
    es.addEventListener("run_started", onAny);
    es.addEventListener("run_completed", onAny);
    es.addEventListener("run_failed", onAny);
    es.addEventListener("error", () => {
      void refreshActiveRun(activeRunId);
    });
    return () => {
      es.close();
    };
  }, [activeRunId, activeRun?.status, refreshActiveRun, activeRun]);

  function onRunCreated(run: DiscoveryRunSummary) {
    setRuns((prev) => [run, ...prev]);
    setActiveRunId(run.run_id);
    setActiveRun({ ...run, candidates: [] });
  }

  async function onSelectRun(runId: string) {
    setActiveRunId(runId);
    await refreshActiveRun(runId);
  }

  async function onDeleteRun() {
    if (!activeRunId) return;
    if (!confirm("이 run 을 삭제할까요? 후보들도 함께 삭제됩니다.")) return;
    try {
      await deleteDiscoveryRun(activeRunId);
      setActiveRunId(null);
      setActiveRun(null);
      await refreshRunsList();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function onRecompute(weights: Record<WeightDimension, number>) {
    if (!activeRunId) return;
    setRecomputing(true);
    setError(null);
    try {
      await recomputeDiscovery(activeRunId, { weights });
      await refreshActiveRun(activeRunId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRecomputing(false);
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Discovery</h1>
        <p className="mt-1 text-sm text-slate-500">
          RAG 기반 BD 타겟 발굴 — 6차원 점수 + 외부 weights 로 tier 결정. weight
          슬라이더로 LLM 호출 0원으로 재계산 가능.
        </p>
      </div>

      <DiscoveryRunForm
        onRunCreated={onRunCreated}
        disabled={
          activeRun?.status === "queued" || activeRun?.status === "running"
        }
      />

      <hr className="border-slate-200" />

      <section className="space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-lg font-medium">결과 (티어리스트)</h2>
          {runs.length > 0 && (
            <select
              value={activeRunId ?? ""}
              onChange={(e) => onSelectRun(e.target.value)}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-sm"
            >
              {runs.map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {r.created_at.slice(0, 19).replace("T", " ")} — {r.product} ·{" "}
                  {r.candidate_count} cands · {r.status}
                </option>
              ))}
            </select>
          )}
          {activeRunId && (
            <button
              type="button"
              onClick={onDeleteRun}
              className="rounded border border-rose-300 bg-white px-3 py-1 text-xs text-rose-700 hover:bg-rose-50"
            >
              run 삭제
            </button>
          )}
        </div>

        {loading && <p className="text-sm text-slate-500">불러오는 중...</p>}

        {!loading && runs.length === 0 && (
          <EmptyState
            title="아직 발굴된 후보가 없습니다."
            description="위 폼에서 첫 Discovery 를 실행해보세요. RAG namespace 가 비어있으면 RAG 탭에서 먼저 docs 를 업로드하세요."
            ctaLabel="RAG 탭으로"
            ctaHref="/rag"
          />
        )}

        {activeRun && (
          <RunDetail
            detail={activeRun}
            onRecompute={onRecompute}
            recomputing={recomputing}
            onChanged={() => activeRunId && refreshActiveRun(activeRunId)}
            error={error}
          />
        )}
      </section>
    </div>
  );
}

function RunDetail({
  detail,
  onRecompute,
  recomputing,
  onChanged,
  error,
}: {
  detail: DiscoveryRunDetail;
  onRecompute: (w: Record<WeightDimension, number>) => Promise<void>;
  recomputing: boolean;
  onChanged: () => void;
  error: string | null;
}) {
  const tiers = ["S", "A", "B", "C"] as const;
  return (
    <div className="space-y-4">
      <div className="rounded-md border border-slate-200 bg-white p-4 text-sm shadow-sm">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
          <span>
            <strong>Status:</strong>{" "}
            <StatusPill status={detail.status} />
          </span>
          <span className="text-xs text-slate-500">
            run_id <code>{detail.run_id}</code>
          </span>
          <span className="text-xs text-slate-500">
            namespace <code>{detail.namespace}</code> · region {detail.region} ·
            seed {detail.seed_doc_count} docs / {detail.seed_chunk_count} chunks
          </span>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
          {tiers.map((t) => (
            <span key={t} className="text-slate-600">
              {t}: <strong>{detail.tier_distribution[t] ?? 0}</strong>
            </span>
          ))}
          {detail.usage && Object.keys(detail.usage).length > 0 && (
            <span className="text-slate-500">
              · in {detail.usage.input_tokens ?? 0} / out{" "}
              {detail.usage.output_tokens ?? 0}
              {detail.usage.cache_read
                ? ` / cache_read ${detail.usage.cache_read}`
                : ""}
            </span>
          )}
        </div>
        {detail.status === "failed" && detail.error_message && (
          <p className="mt-2 text-xs text-red-600">{detail.error_message}</p>
        )}
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      <WeightSliders onRecompute={onRecompute} busy={recomputing} />

      <CandidateTable candidates={detail.candidates} onChanged={onChanged} />
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
