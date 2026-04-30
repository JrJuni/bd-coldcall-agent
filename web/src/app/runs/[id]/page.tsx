"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { getRun, patchRun, sseUrl } from "@/lib/api";
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
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<string>("");
  const [saving, setSaving] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);

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
      source.close();
    };
    return () => {
      source.close();
    };
  }, [runId]);

  function startEdit() {
    setDraft(run?.proposal_md ?? "");
    setEditing(true);
    setSaveErr(null);
  }

  async function saveEdit() {
    setSaving(true);
    setSaveErr(null);
    try {
      const updated = await patchRun(runId, { proposal_md: draft });
      setRun(updated);
      setEditing(false);
    } catch (err) {
      setSaveErr(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  function cancelEdit() {
    setEditing(false);
    setSaveErr(null);
  }

  function downloadMarkdown() {
    if (!run?.proposal_md) return;
    const blob = new Blob([run.proposal_md], {
      type: "text/markdown;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const safeCompany = (run.company || "proposal").replace(/[^A-Za-z0-9_-]/g, "_");
    const stamp = (run.created_at || "").slice(0, 10).replace(/-/g, "");
    const filename = `${safeCompany}_${stamp || "proposal"}.md`;
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

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
            <li>cache_read: {run?.usage?.cache_read_input_tokens ?? 0}</li>
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
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-600">Proposal</h2>
            <div className="flex gap-2">
              {!editing && (
                <>
                  <button
                    type="button"
                    onClick={startEdit}
                    className="rounded border border-slate-300 px-2.5 py-1 text-xs hover:bg-slate-50"
                  >
                    편집
                  </button>
                  <button
                    type="button"
                    onClick={downloadMarkdown}
                    className="rounded border border-slate-300 px-2.5 py-1 text-xs hover:bg-slate-50"
                  >
                    .md 다운로드
                  </button>
                </>
              )}
              {editing && (
                <>
                  <button
                    type="button"
                    onClick={saveEdit}
                    disabled={saving}
                    className="rounded bg-slate-900 px-2.5 py-1 text-xs text-white hover:bg-slate-800 disabled:opacity-50"
                  >
                    {saving ? "저장 중..." : "저장"}
                  </button>
                  <button
                    type="button"
                    onClick={cancelEdit}
                    disabled={saving}
                    className="rounded border border-slate-300 px-2.5 py-1 text-xs hover:bg-slate-50 disabled:opacity-50"
                  >
                    취소
                  </button>
                </>
              )}
            </div>
          </div>

          {editing ? (
            <>
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                rows={24}
                className="block w-full rounded border border-slate-300 px-3 py-2 font-mono text-xs"
                spellCheck={false}
              />
              {saveErr && (
                <p className="mt-2 text-xs text-red-600">{saveErr}</p>
              )}
              <p className="mt-2 text-xs text-slate-500">
                편집한 markdown 은 process-local RunStore 에 저장됩니다 (재시작 시
                휘발). DB 영속화는 후속 PR.
              </p>
            </>
          ) : (
            <div className="prose prose-slate max-w-none [&_h2]:mt-6 [&_h2]:text-lg [&_h3]:mt-4 [&_p]:leading-relaxed">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {run.proposal_md}
              </ReactMarkdown>
            </div>
          )}
        </section>
      )}

      {connError && <p className="text-sm text-red-600">{connError}</p>}
    </div>
  );
}
