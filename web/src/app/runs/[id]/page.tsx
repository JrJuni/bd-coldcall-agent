"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { getRun, sseUrl } from "@/lib/api";
import type { RunSummary } from "@/lib/types";
import { StageProgress } from "@/components/StageProgress";

const SSE_EVENT_KINDS = [
  "run_queued",
  "run_started",
  "stage_started",
  "stage_completed",
  "run_completed",
  "run_failed",
];

export default function RunDetailPage() {
  const params = useParams<{ id: string }>();
  const runId = decodeURIComponent(params.id);
  const [run, setRun] = useState<RunSummary | null>(null);
  const [connError, setConnError] = useState<string | null>(null);

  // Initial authoritative snapshot
  useEffect(() => {
    let cancelled = false;
    getRun(runId)
      .then((r) => {
        if (!cancelled) setRun(r);
      })
      .catch((err) => {
        if (!cancelled) setConnError(String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [runId]);

  // SSE subscription — on every progress event, refetch the full summary
  // so the UI reflects authoritative state (stages_completed, usage, etc.).
  useEffect(() => {
    const source = new EventSource(sseUrl(runId));
    const onEvent = () => {
      getRun(runId)
        .then(setRun)
        .catch(() => {});
    };
    SSE_EVENT_KINDS.forEach((kind) => {
      source.addEventListener(kind, onEvent);
    });
    source.onerror = () => {
      // The backend closes the stream when the run reaches a terminal state.
      source.close();
    };
    return () => {
      source.close();
    };
  }, [runId]);

  return (
    <div className="space-y-8">
      <section>
        <h1 className="text-2xl font-semibold">
          {run?.company ?? "…"}{" "}
          <span className="text-base font-normal text-slate-500">
            — {run?.industry ?? ""}
          </span>
        </h1>
        <p className="text-sm text-slate-500">
          run_id: <code>{runId}</code>
        </p>
      </section>

      <section className="grid gap-6 md:grid-cols-2">
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <h2 className="mb-2 text-sm font-semibold text-slate-600">
            Pipeline progress
          </h2>
          <StageProgress
            stagesCompleted={run?.stages_completed ?? []}
            currentStage={run?.current_stage ?? null}
            failedStage={run?.failed_stage ?? null}
          />
          <p className="mt-3 text-xs text-slate-500">
            status: <b>{run?.status ?? "…"}</b>
            {run?.duration_s != null && ` · ${run.duration_s}s`}
          </p>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <h2 className="mb-2 text-sm font-semibold text-slate-600">Counts</h2>
          <ul className="space-y-1 text-sm text-slate-700">
            <li>Articles searched: {run?.article_counts?.searched ?? 0}</li>
            <li>Articles fetched: {run?.article_counts?.fetched ?? 0}</li>
            <li>Articles processed: {run?.article_counts?.processed ?? 0}</li>
            <li>Proposal points: {run?.proposal_points_count ?? 0}</li>
          </ul>
          <h3 className="mb-2 mt-4 text-sm font-semibold text-slate-600">
            Sonnet usage
          </h3>
          <ul className="space-y-1 font-mono text-xs text-slate-600">
            <li>in: {run?.usage?.input_tokens ?? 0}</li>
            <li>out: {run?.usage?.output_tokens ?? 0}</li>
            <li>
              cache_read: {run?.usage?.cache_read_input_tokens ?? 0}
            </li>
            <li>
              cache_write:{" "}
              {run?.usage?.cache_creation_input_tokens ?? 0}
            </li>
          </ul>
        </div>
      </section>

      {run?.errors && run.errors.length > 0 && (
        <section className="rounded-lg border border-red-200 bg-red-50 p-4">
          <h2 className="mb-2 text-sm font-semibold text-red-700">Errors</h2>
          <ul className="space-y-1 text-sm text-red-800">
            {run.errors.map((e, i) => (
              <li key={i}>
                <code>[{String(e.stage)}]</code> {String(e.error_type)}:{" "}
                {String(e.message)}
              </li>
            ))}
          </ul>
        </section>
      )}

      {run?.proposal_md && (
        <section className="rounded-lg border border-slate-200 bg-white p-6">
          <h2 className="mb-4 text-sm font-semibold text-slate-600">
            Proposal
          </h2>
          <div className="prose prose-slate max-w-none [&_h2]:mt-6 [&_h2]:text-lg [&_h3]:mt-4 [&_p]:leading-relaxed">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {run.proposal_md}
            </ReactMarkdown>
          </div>
        </section>
      )}

      {connError && <p className="text-sm text-red-600">{connError}</p>}
    </div>
  );
}
