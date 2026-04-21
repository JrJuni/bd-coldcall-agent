"use client";

import { useEffect, useState } from "react";

import { getIngestStatus, triggerIngest } from "@/lib/api";
import type { IngestStatus } from "@/lib/types";

export default function RagPage() {
  const [status, setStatus] = useState<IngestStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [notion, setNotion] = useState(false);
  const [force, setForce] = useState(false);

  async function refresh() {
    try {
      const s = await getIngestStatus();
      setStatus(s);
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function onTrigger(dryRun: boolean) {
    setBusy(true);
    setMsg(null);
    setErr(null);
    try {
      const r = await triggerIngest({ notion, force, dry_run: dryRun });
      setMsg(
        `Task ${r.task_id}: ${r.status}${r.message ? " — " + r.message : ""}`
      );
      setTimeout(refresh, 1500);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-2xl space-y-6">
      <h1 className="text-2xl font-semibold">RAG index</h1>

      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="mb-2 text-sm font-semibold text-slate-600">Status</h2>
        {status ? (
          <ul className="space-y-1 text-sm text-slate-700">
            <li>
              Manifest: <code>{status.manifest_path}</code> (
              {status.manifest_exists ? "found" : "missing"})
            </li>
            <li>Version: {status.version ?? "—"}</li>
            <li>Updated: {status.updated_at ?? "—"}</li>
            <li>Documents: {status.document_count}</li>
            <li>Chunks: {status.chunk_count}</li>
            <li>
              By source type:{" "}
              {Object.entries(status.by_source_type)
                .map(([k, v]) => `${k}=${v}`)
                .join(", ") || "—"}
            </li>
          </ul>
        ) : (
          <p className="text-sm text-slate-500">Loading…</p>
        )}
      </section>

      <section className="space-y-3 rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-slate-600">
          Trigger re-index
        </h2>
        <div className="flex gap-4 text-sm">
          <label className="inline-flex items-center gap-2">
            <input
              type="checkbox"
              checked={notion}
              onChange={(e) => setNotion(e.target.checked)}
            />
            Notion
          </label>
          <label className="inline-flex items-center gap-2">
            <input
              type="checkbox"
              checked={force}
              onChange={(e) => setForce(e.target.checked)}
            />
            Force
          </label>
        </div>
        <div className="flex gap-2">
          <button
            disabled={busy}
            onClick={() => onTrigger(true)}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50 disabled:opacity-50"
          >
            Dry run
          </button>
          <button
            disabled={busy}
            onClick={() => onTrigger(false)}
            className="rounded-md bg-slate-900 px-3 py-1.5 text-sm text-white hover:bg-slate-800 disabled:opacity-50"
          >
            Re-index
          </button>
        </div>
        {msg && <p className="text-sm text-emerald-700">{msg}</p>}
        {err && <p className="text-sm text-red-600">{err}</p>}
      </section>

      <p className="text-xs text-slate-500">
        Upload / delete UI is out of scope for the Phase 7 MVP — see{" "}
        <code>docs/status.md</code> 장기 과제.
      </p>
    </div>
  );
}
